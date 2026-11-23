"""概要: 保存データで条件群の全32構成と時系列選択を精査し、研究成果物を保存する。
作成日: 2026-11-13。
入力: --dataset 保存JSON、--output 未使用フォルダー、任意の--config。
出力: 全構成CSV/JSON、選択根拠、安定性診断、Markdown、SHA付きmanifest。成功0・失敗非0。
実行例: uv run python scripts/run_jra_conditions_search.py --dataset artifacts/example/dataset.json --output artifacts/example-search
注意事項: DB接続・外部通信・購入なし。入力/既存出力を変更しない。全期間首位は探索結果。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jra_srb.jra_conditions_search import inspect_subsets, render_search
from jra_srb.jra_race_conditions import load_config
from jra_srb.jra_race_conditions_report import Outputs
from jra_srb.jra_research_contracts import ResearchError


def main(argv: list[str] | None = None) -> int:
    """固定した探索を一度実行し、全候補と選択過程を新規フォルダーへ保存する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/research/race_conditions_elizabeth_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    outputs = None
    try:
        config = load_config(args.config)
        outputs = Outputs(args.output, "search-subsets", config)
        dataset = json.loads(args.dataset.read_text(encoding="utf-8-sig"))
        result = inspect_subsets(dataset, config)
        outputs.json("summary.json", {k: v for k, v in result.items() if k not in
                     ("predictions", "annual", "selection", "leave_one_race_out", "addition_diagnostics")})
        outputs.json("predictions.json", result["predictions"])
        outputs.json("selection.json", result["selection"])
        outputs.json("stability.json", {k: result[k] for k in
                     ("paired_intervals", "selection_counts", "leave_one_race_out", "addition_diagnostics")})
        outputs.csv("annual.csv", result["annual"], ["pattern", "mask", "race_key", "race_date", "venue_code",
                    "races", "runners", "brier", "logloss", "top1_top3_hit", "top3_captured"])
        flat = [{"pattern": p["pattern"], "mask": p["mask"], "groups": "＋".join(p["groups"]),
                 "group_count": p["group_count"], **p["all"], "better_than_full_years": p["better_than_full_years"],
                 "worse_than_full_years": p["worse_than_full_years"]} for p in result["patterns"]]
        outputs.csv("patterns.csv", flat, list(flat[0]))
        outputs.markdown(render_search(result))
        code = [ROOT / "src/jra_srb/jra_conditions_search.py", Path(__file__)]
        outputs.finish(input_sha256=dataset["input_sha256"], availability="retrospective_research_only",
                       search_protocol=result["protocol"], evaluated_races=result["patterns"][0]["all"]["races"],
                       outer_races=result["outer_summary"]["past_selected"]["races"],
                       search_code_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code})
        print(json.dumps({"status": "complete", "output": str(outputs.path),
                          "candidate": result["final_research_candidate"]["pattern"], "verdict": result["verdict"]}))
        return 0
    except Exception as error:
        if outputs is not None:
            outputs.fail(error)
        print(json.dumps({"status": "failed", "reason": getattr(error, "reason", "search_execution_failed"),
                          "error_type": type(error).__name__}), file=sys.stderr)
        return error.exit_code if isinstance(error, ResearchError) else 4


if __name__ == "__main__":
    raise SystemExit(main())
