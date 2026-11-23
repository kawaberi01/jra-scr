"""概要: 固定した69候補の仮説比較を実行し、研究版の候補と検証結果を保存する。
作成日: 2026-11-13。
入力: --dataset 保存JSON、--output 未使用フォルダー、任意--config。
出力: 全候補/予測/根拠/選択/指標JSON・CSV、レポート、SHA付きmanifest。正常0・失敗非0。
実行例: uv run python scripts/run_jra_conditions_refinement.py --dataset artifacts/example/dataset.json --output artifacts/example-refinement
注意事項: 外部取得・DB・既定変更・購入なし。既存出力を上書きしない。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jra_srb.jra_conditions_refinement import refine, render_refinement
from jra_srb.jra_race_conditions import load_config
from jra_srb.jra_race_conditions_report import Outputs
from jra_srb.jra_research_contracts import ResearchError


def main(argv: list[str] | None = None) -> int:
    """実入力で比較し、設定・全予測・根拠と採否を新規成果物へ保存する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/research/race_conditions_elizabeth_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    outputs = None
    try:
        config = load_config(args.config)
        outputs = Outputs(args.output, "refine-conditions", config)
        data = json.loads(args.dataset.read_text(encoding="utf-8-sig"))
        result = refine(data, config)
        for name in ("candidates", "predictions", "evidence", "selection"):
            outputs.json(name+".json", result[name])
        outputs.json("summary.json", {k: v for k, v in result.items() if k not in ("predictions", "evidence", "annual", "selection")})
        outputs.csv("annual.csv", result["annual"], ["pattern", "family", "race_key", "race_date", "venue_code", "races", "runners",
                    "brier", "logloss", "top1_top3_hit", "top3_captured"])
        outputs.json("research-candidate.json", {"availability": "research_only", "selected": result["final_research_candidate"],
                     "protocol": result["protocol"], "verdict": result["verdict"], "input_sha256": data["input_sha256"]})
        outputs.markdown(render_refinement(result))
        code = [ROOT / "src/jra_srb/jra_conditions_refinement.py", ROOT / "src/jra_srb/jra_conditions_search.py", Path(__file__)]
        outputs.finish(input_sha256=data["input_sha256"], availability="retrospective_research_only", refinement_protocol=result["protocol"],
                       verdict=result["verdict"], refinement_code_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code})
        print(json.dumps({"status": "complete", "verdict": result["verdict"], "candidate": result["final_research_candidate"]["candidate"]["pattern"],
                          "output": str(outputs.path)}))
        return 0
    except Exception as error:
        if outputs is not None:
            outputs.fail(error)
        print(json.dumps({"status": "failed", "reason": getattr(error, "reason", "refinement_execution_failed"),
                          "error_type": type(error).__name__}), file=sys.stderr)
        return error.exit_code if isinstance(error, ResearchError) else 4


if __name__ == "__main__":
    raise SystemExit(main())
