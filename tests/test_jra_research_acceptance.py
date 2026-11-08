"""概要: SQL研究受入監査の重要な失敗分類を合成台帳で検証する。
作成日: 2026-10-15
入力: tmp_path上の合成受入台帳、manifest、config、source。
出力: pytestの単体試験結果。
実行例: uv run pytest -q tests/test_jra_research_acceptance.py
注意事項: 実DB・HTTP・研究コードを実行せず、テスト用一時ファイルだけを作成する。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from jra_srb import jra_research_acceptance as acceptance


@pytest.fixture
def audit_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """実装の定義導出境界を省略し、監査本体を一時rootで動かす。"""
    monkeypatch.setattr(acceptance._Audit, "structure", lambda self: {})
    monkeypatch.setattr(acceptance._Audit, "definition_sets", lambda self, by_id: None)

    def run(registry: dict) -> dict:
        """指定台帳を一時rootへ保存し、公開監査関数の結果を返す。"""
        if not registry.get("source_fingerprints"):
            source = tmp_path / "source.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            registry["source_fingerprints"] = {"source.py": hashlib.sha256(source.read_bytes()).hexdigest()}
        registry_path = tmp_path / "acceptance_registry.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        return acceptance.audit_acceptance_registry(registry_path, project_root=tmp_path)

    return tmp_path, run


def _registry(**values) -> dict:
    """監査が読む最小のschema_version 1台帳を作る。"""
    registry = {
        "schema_version": 1,
        "profiles": [],
        "phases": [],
        "completion_gates": [],
        "source_fingerprints": {},
        "evidence": {},
    }
    registry.update(values)
    return registry


def test_source_fingerprint_change_is_reported(audit_harness):
    """source内容のSHA不一致を監査エラーとして検出する。"""
    root, run = audit_harness
    source = root / "sample.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    registry = _registry(source_fingerprints={"sample.py": hashlib.sha256(b"VALUE = 1\n").hexdigest()})

    result = run(registry)

    assert result["status"] == "failed"
    assert any(error["code"] == "source_fingerprint_changed" for error in result["errors"])


def test_shipped_registry_is_valid_pending_and_incomplete(tmp_path: Path):
    """実registryのpending状態を維持し、監査passedと全体未完了を確認する。"""
    result = _audit_shipped_registry(tmp_path)

    assert result["status"] == "passed"
    assert result["overall_complete"] is False
    assert result["pending"]


@pytest.mark.parametrize("declaration,present", [("VALUE: int = 1", True), ("VALUE: int", False)])
def test_annotated_symbol_requires_assigned_value(audit_harness, declaration, present):
    """型注釈付き代入は実在定数と認識し、注釈だけの宣言は採用しない。"""
    root, run = audit_harness
    source = root / "sample.py"
    source.write_text(declaration + "\n", encoding="utf-8")
    registry = _registry(
        profiles=[{"profile_id": "p1", "status": "pending",
                   "feature_contract": {"code_symbols": ["sample.py::VALUE"]}}],
        source_fingerprints={"sample.py": hashlib.sha256(source.read_bytes()).hexdigest()},
    )
    result = run(registry)
    missing = any(error["code"] == "symbol_missing" for error in result["errors"])
    assert missing is not present


def test_shipped_registry_missing_ten_trial_variant_fails_ast_comparison(tmp_path: Path):
    """実registryからten-trials variantを1件除くと実AST照合で失敗する。"""
    registry = _load_shipped_registry(tmp_path)
    profile = next(row for row in registry["profiles"] if row["profile_id"] == "ten_trials_sql_v1")
    profile["output_variants"].pop()
    result = _audit_registry_file(tmp_path, registry)

    assert result["status"] == "failed"
    mismatch = next(error for error in result["errors"] if error["code"] == "definition_set_mismatch")
    assert mismatch["path"] == "ten_trials_sql_v1/output_variants"
    assert len(mismatch["details"]["missing"]) == 1
    assert mismatch["details"]["unexpected"] == []


def test_verified_without_reviewed_acceptance_evidence_is_rejected(audit_harness):
    """完了manifestでも人の証拠レビュー未完了ならverified宣言を拒否する。"""
    root, run = audit_harness
    _write_evidence(root, status="complete", evidence_status="pending")
    record = _evidence_record(observed_manifest_status="complete", evidence_status="pending")
    record["manifest_sha256"] = hashlib.sha256((root / "runs/run1/manifest.json").read_bytes()).hexdigest()
    registry = _registry(
        profiles=[{"profile_id": "p1", "status": "verified", "evidence": ["run1"]}],
        evidence={"run1": record},
    )

    result = run(registry)

    assert result["status"] == "failed"
    assert any(error["code"] == "verified_evidence_not_reviewed" for error in result["errors"])


@pytest.mark.parametrize("terminal_status", ["complete", "failed"])
def test_running_manifest_progress_requires_update_not_corruption(audit_harness, terminal_status):
    """runningからterminalへのmanifest進行を破損でなく更新要確認へ分類する。"""
    root, run = audit_harness
    _write_evidence(root, status=terminal_status)
    record = _evidence_record(observed_manifest_status="running")
    registry = _registry(evidence={"run1": record})

    result = run(registry)

    assert result["status"] == "needs_update"
    assert result["errors"] == []
    assert [item["code"] for item in result["updates_required"]] == ["evidence_progress_requires_update"]


def test_changed_history_model_is_reported(audit_harness):
    """R01 history modelの内容改変をmanifest整合エラーとして検出する。"""
    root, run = audit_harness
    run_dir = root / "runs" / "run1"
    run_dir.mkdir(parents=True, exist_ok=True)
    model_path = run_dir / "model_history.json"
    model = {"version": 1}
    contract = {"features": ["synthetic"]}
    def canonical_bytes(value: dict) -> bytes:
        """wrapper署名用のJSONを実装と同じ正規化でbytes化する。"""
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")

    contract_digest = hashlib.sha256(canonical_bytes(contract)).hexdigest()
    model_path.write_text(json.dumps({"model": model, "contract": contract, "contract_sha256": contract_digest}), encoding="utf-8")
    model_digest = hashlib.sha256(canonical_bytes(model)).hexdigest()
    manifest = {
        "run_id": "run1",
        "command": "history",
        "status": "complete",
        "model_sha256": model_digest,
        "feature_contract_sha256": contract_digest,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "config.json").write_text(json.dumps({"profile_id": "p1"}), encoding="utf-8")
    record = _evidence_record(observed_manifest_status="complete")
    record["command"] = "history"
    record["manifest_sha256"] = hashlib.sha256(json.dumps(manifest).encode("utf-8")).hexdigest()
    record["present_files"] = ["manifest.json", "config.json", "model_history.json"]

    registry = _registry(evidence={"run1": record})
    assert run(registry)["status"] == "passed"

    model_path.write_text(json.dumps({"model": {"version": 2}, "contract": contract, "contract_sha256": contract_digest}), encoding="utf-8")
    result = run(registry)

    assert result["status"] == "failed"
    assert [error["code"] for error in result["errors"]] == ["evidence_model_changed"]


def test_reviewed_metric_artifact_content_change_is_detected(audit_harness):
    """manifestが同じでも受入済みmetricsの改変をfile内容SHAで検出する。"""
    root, run = audit_harness
    _write_evidence(root, status="complete")
    metric = root / "runs/run1/metrics.json"
    metric.write_text('{"win": 0.5}', encoding="utf-8")
    record = _evidence_record(observed_manifest_status="complete")
    record["manifest_sha256"] = hashlib.sha256((metric.parent / "manifest.json").read_bytes()).hexdigest()
    record["present_files"].append("metrics.json")
    record["artifact_sha256"] = {name: hashlib.sha256((metric.parent / name).read_bytes()).hexdigest()
                                 for name in ("config.json", "metrics.json")}
    registry = _registry(evidence={"run1": record})
    assert run(registry)["status"] == "passed"
    metric.write_text('{"win": 0.9}', encoding="utf-8")
    result = run(registry)
    assert result["status"] == "failed"
    assert [error["code"] for error in result["errors"]] == ["evidence_artifact_changed"]


def test_verified_case_requires_all_artifact_content_fingerprints(audit_harness):
    """受入caseから参照する証跡は、全許可ファイルの内容SHAがなければ拒否する。"""
    root, run = audit_harness
    _write_evidence(root, status="complete")
    record = _evidence_record(observed_manifest_status="complete")
    record["manifest_sha256"] = hashlib.sha256((root / "runs/run1/manifest.json").read_bytes()).hexdigest()
    registry = _registry(profiles=[{"profile_id": "p1", "status": "verified", "evidence": ["run1"]}],
                         evidence={"run1": record})
    assert any(e["code"] == "verified_artifact_fingerprints_missing" for e in run(registry)["errors"])
    record["artifact_sha256"] = {"config.json": hashlib.sha256((root / "runs/run1/config.json").read_bytes()).hexdigest()}
    assert run(registry)["status"] == "passed"


def _load_shipped_registry(tmp_path: Path) -> dict:
    """実registryをメモリへ複製し、実在manifestの観測hash/statusを同期する。"""
    project_root = Path(__file__).resolve().parents[1]
    source = project_root / "configs/research/acceptance_registry.json"
    registry = json.loads(source.read_text(encoding="utf-8-sig"))
    for item in registry.get("evidence", {}).values():
        manifest_path = project_root / item["path"]
        if manifest_path.is_file():
            payload = manifest_path.read_bytes()
            manifest = json.loads(payload.decode("utf-8-sig"))
            item["manifest_sha256"] = hashlib.sha256(payload).hexdigest()
            item["observed_manifest_status"] = manifest.get("status")
    return registry


def _audit_shipped_registry(tmp_path: Path) -> dict:
    """実rootを読み取り対象にして、複製registryをtmp_pathから監査する。"""
    return _audit_registry_file(tmp_path, _load_shipped_registry(tmp_path))


def _audit_registry_file(tmp_path: Path, registry: dict) -> dict:
    """台帳dictをtmp_pathへ保存し、実案件rootを対象に公開監査関数を呼ぶ。"""
    project_root = Path(__file__).resolve().parents[1]
    registry_path = tmp_path / "acceptance_registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    return acceptance.audit_acceptance_registry(registry_path, project_root=project_root)


def _evidence_record(*, observed_manifest_status: str = "running", evidence_status: str = "verified") -> dict:
    """合成manifestと対応configを指す台帳証拠行を返す。"""
    manifest = {"run_id": "run1", "command": "train", "status": "running"}
    payload = json.dumps(manifest).encode("utf-8")
    return {
        "path": "runs/run1/manifest.json",
        "run_id": "run1",
        "command": "train",
        "profile_id": "p1",
        "evidence_status": evidence_status,
        "observed_manifest_status": observed_manifest_status,
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "recorded_hashes": {},
        "present_files": ["manifest.json", "config.json"],
    }


def _write_evidence(root: Path, *, status: str, evidence_status: str = "verified") -> None:
    """合成runのmanifestとprofile configを一時rootへ作成する。"""
    run_dir = root / "runs" / "run1"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": "run1", "command": "train", "status": status, "models": {}}),
        encoding="utf-8",
    )
    (run_dir / "config.json").write_text(json.dumps({"profile_id": "p1"}), encoding="utf-8")
