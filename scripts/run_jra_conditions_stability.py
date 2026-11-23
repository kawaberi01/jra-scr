"""概要: 69候補の保存結果を検証し、8安定化方式の時系列比較を保存する。
作成日: 2026-11-13。
入力: --source 先行比較フォルダー、--dataset 元保存JSON、--output 未使用フォルダー。
出力: 全予測・指標・選択JSON/CSV、レポート、SHA付きmanifest。正常0・失敗非0。
実行例: uv run python scripts/run_jra_conditions_stability.py --source artifacts/refinement --dataset artifacts/input/dataset.json --output artifacts/stability
注意事項: DB・外部取得なし。先行成果物のSHA不一致で停止する。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jra_srb.jra_conditions_stability import render_stability, stabilize
from jra_srb.jra_race_conditions import load_config, require
from jra_srb.jra_race_conditions_report import Outputs
from jra_srb.jra_research_contracts import ResearchError


def load_source(path: Path) -> dict:
    """成功済み先行出力のSHAを検証し、必要な予測と数値化した年度CSVを読む。"""
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["status"] == "complete", "stability_source_status")
    for name, sha in manifest["files_sha256"].items():
        require(Path(name).name == name and hashlib.sha256((path/name).read_bytes()).hexdigest() == sha, "stability_source_sha")
    result = json.loads((path / "summary.json").read_text(encoding="utf-8"))
    result["predictions"] = json.loads((path / "predictions.json").read_text(encoding="utf-8"))
    with (path / "annual.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        for key in ("races", "runners"):
            row[key] = int(row[key])
        for key in ("brier", "logloss", "top1_top3_hit", "top3_captured"):
            row[key] = float(row[key])
    result["annual"] = rows
    result["source_manifest_sha256"] = hashlib.sha256((path / "manifest.json").read_bytes()).hexdigest()
    return result


def main(argv: list[str] | None = None) -> int:
    """先行出力を変更せず固定した安定化比較を実行し、結果を保存する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/research/race_conditions_elizabeth_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    outputs = None
    try:
        config = load_config(args.config)
        outputs = Outputs(args.output, "stabilize-conditions", config)
        source = load_source(args.source)
        dataset = json.loads(args.dataset.read_text(encoding="utf-8-sig"))
        result = stabilize(source, dataset)
        for key in ("predictions", "policy_selection"):
            outputs.json(key+".json", result[key])
        outputs.json("summary.json", {k: v for k, v in result.items() if k not in ("predictions", "annual", "policy_selection")})
        outputs.csv("annual.csv", result["annual"], ["pattern", "race_date", "race_key", "venue_code", "races", "runners",
                    "brier", "logloss", "top1_top3_hit", "top3_captured"])
        outputs.markdown(render_stability(result))
        code = [ROOT / "src/jra_srb" / name for name in
                ("jra_conditions_refinement.py", "jra_conditions_search.py", "jra_conditions_stability.py")]
        code.append(Path(__file__))
        outputs.finish(input_sha256=dataset["input_sha256"], source_manifest_sha256=source["source_manifest_sha256"],
                       availability="retrospective_research_only", stability_protocol=result["protocol"],
                       stability_code_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code})
        print(json.dumps({"status": "complete", "qualifying": result["qualifying_policies"], "output": str(outputs.path)}))
        return 0
    except Exception as error:
        if outputs is not None:
            outputs.fail(error)
        print(json.dumps({"status": "failed", "reason": getattr(error, "reason", "stability_execution_failed"),
                          "error_type": type(error).__name__}), file=sys.stderr)
        return error.exit_code if isinstance(error, ResearchError) else 4


if __name__ == "__main__":
    raise SystemExit(main())
