"""概要: 元データを複製せず研究の契約・モデル・予測・評価だけを保存する。
作成日: 2026-10-15
入力: 非秘密設定、来歴、学習モデル、予測、評価。
出力: artifacts/jra_research/runs内の上書きしない実験記録。
実行例: uv run python scripts/run_jra_research.py run --config configs/research/cross_pool_sql_masked_v2.json
注意事項: 生のSQL行・市場明細・全特徴量ベクトルを保存しない。
"""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import platform
import re
import subprocess
import uuid

from .jra_research_contracts import CONTRACT_VERSION, ResearchError, canonical_json


ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "artifacts" / "jra_research" / "runs"
JSON_NAMES = frozenset(("config.json", "manifest.json", "coverage.json", "metrics.json", "failure.json", "preflight.json", "model_history.json"))


def code_identity() -> dict:
    """dirty作業ツリーでも研究コード実内容を特定できるhashを返す。"""
    files = sorted((ROOT / "src/jra_srb").glob("jra_research_*.py")) + [ROOT / "scripts/run_jra_research.py"]
    files += [ROOT / "src/jra_srb" / name for name in ("jra_history_dataset.py", "jra_recent_form_dataset.py", "jra_history_model.py")]
    hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.exists()}
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    dependencies = {}
    for name in ("mssql-python", "numpy", "scipy", "scikit-learn", "joblib", "threadpoolctl"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    return {"git_head": result.stdout.strip() if result.returncode == 0 else None,
            "code_sha256": hashes, "python": platform.python_version(), "dependencies": dependencies}


def existing_run(run_id: str) -> Path:
    """run IDのpath逸脱を拒否し既存manifestの所在を返す。"""
    if not re.fullmatch(r"\d{8}T\d{6}Z_[0-9a-f]{32}", run_id):
        raise ResearchError("invalid_run_id", 2)
    path = RUN_ROOT / run_id
    if not (path / "manifest.json").is_file():
        raise ResearchError("missing_run", 2)
    return path


def verify_replay_outputs(original: dict, metrics: dict, predictions_sha256: str) -> None:
    """入力一致後も計算結果が旧runと異なれば再現成功と報告しない。"""
    from .jra_research_contracts import digest
    if original.get("metrics_sha256") != digest(metrics) or original.get("predictions_sha256") != predictions_sha256:
        raise ResearchError("replay_output_changed", 5)


class RunArtifacts:
    """許可名の成果物のみを新規runへ保存し、状態をatomicに公開する。"""

    def __init__(self, config: dict, command: str):
        """一意runを作りrunning状態と設定を先に保存する。"""
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex
        self.path = RUN_ROOT / self.run_id
        self.path.mkdir(parents=True, exist_ok=False)
        self.manifest = {"run_id": self.run_id, "command": command, "status": "running",
                         "contract_version": CONTRACT_VERSION, "started_at_utc": datetime.now(timezone.utc).isoformat(),
                         **code_identity()}
        self.write_json("config.json", config)
        self.write_json("manifest.json", self.manifest)

    def write_json(self, name: str, value: dict) -> None:
        """固定allowlistのJSONだけを一時名からatomicに置き換える。"""
        if name not in JSON_NAMES:
            raise ResearchError("forbidden_artifact", 2)
        target = self.path / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(target)

    def write_excluded(self, rows: list[dict]) -> None:
        """元データなしのレースキーと除外理由だけを保存する。"""
        with (self.path / "excluded.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                if set(row) != {"race_key", "reason"}:
                    raise ResearchError("forbidden_excluded_payload", 2)
                stream.write(canonical_json(row) + "\n")

    def write_predictions(self, rows: list[dict]) -> str:
        """予測を逐次保存し、一括JSONを作らずcanonical配列と同じSHAを返す。"""
        allowed = {"race_key", "race_date", "venue", "variant", "split", "horses", "probability", "target", "ticket"}
        content_hash = hashlib.sha256(b"[")
        with (self.path / "predictions.jsonl.gz").open("xb") as file:
            with gzip.GzipFile(fileobj=file, mode="wb", mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as stream:
                    for index, row in enumerate(rows):
                        if set(row) != allowed:
                            raise ResearchError("forbidden_prediction_payload", 2)
                        encoded = canonical_json(row)
                        stream.write(encoded + "\n")
                        if index:
                            content_hash.update(b",")
                        content_hash.update(encoded.encode("utf-8"))
        content_hash.update(b"]")
        return content_hash.hexdigest()

    def write_models(self, models: dict) -> None:
        """M1が宣言したbasic/crossだけを保存し内容hashをmanifestへ記録する。"""
        import joblib
        self.manifest["models"] = {}
        for variant, model in models.items():
            if variant not in {"basic", "cross"}:
                raise ResearchError("forbidden_model_artifact", 2)
            target = self.path / f"model_{variant}.joblib"
            if target.exists():
                raise ResearchError("artifact_overwrite_rejected", 2)
            joblib.dump(model, target)
            self.manifest["models"][variant] = {"file": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                                               "feature_contract_sha256": model["contract_sha256"]}

    def finish(self, **details) -> None:
        """全必要処理後にだけcomplete状態を公開する。"""
        if self.manifest["status"] != "running":
            raise ResearchError("invalid_run_state_transition", 2)
        self.manifest.update(details, status="complete", finished_at_utc=datetime.now(timezone.utc).isoformat())
        self.write_json("manifest.json", self.manifest)

    def fail(self, error: ResearchError) -> None:
        """秘密を含まない固定エラー情報だけをfailed記録へ保存する。"""
        report = {"reason": error.reason, "exit_code": error.exit_code, "details": error.details}
        self.write_json("failure.json", report)
        self.manifest.update(status="failed", finished_at_utc=datetime.now(timezone.utc).isoformat(), failure=report)
        self.write_json("manifest.json", self.manifest)
