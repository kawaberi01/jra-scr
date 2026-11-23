"""概要: 同名重賞の既知条件をSQLから取得し、比較・予想・検証を実行する。
作成日: 2026-11-08。
入力: export/analyze/predict、非秘密設定、既存研究reader設定、保存dataset、任意カード。
出力: 明示した新規フォルダーのJSON・CSV・Markdown。正常0、契約不成立は非0。
実行例: uv run python scripts/run_jra_race_conditions.py analyze --dataset artifacts/example/dataset.json --output artifacts/example-analysis
注意事項: SQLはSELECTのみ。既存出力の上書き・外部取得・購入・既定予想変更はしない。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jra_srb.jra_race_conditions import analyze, load_config, predict_card, require
from jra_srb.jra_race_conditions_report import Outputs, render_prediction, save_analysis
from jra_srb.jra_research_contracts import ResearchError, digest


def load_dataset(path: str | Path) -> dict:
    """保存入力の内容SHAを検査し、編集・破損した入力を拒否する。"""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    require(data.get("input_sha256") == digest({k: v for k, v in data.items() if k != "input_sha256"}), "conditions_dataset_sha")
    return data


def main(argv: list[str] | None = None) -> int:
    """指定された一操作を実行し、失敗時も秘密を含まない証跡を残す。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("export", "analyze", "predict"))
    parser.add_argument("--config", type=Path, default=ROOT / "configs/research/race_conditions_elizabeth_v1.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--card", type=Path)
    args = parser.parse_args(argv)
    outputs = None
    reader = None
    try:
        config = load_config(args.config)
        outputs = Outputs(args.output, args.command, config)
        card = json.loads(args.card.read_text(encoding="utf-8-sig")) if args.card else None
        if args.command == "export":
            require(args.dataset is None, "conditions_export_dataset_argument")
            from jra_srb.jra_race_conditions_sql import ConditionsReader, export_dataset
            with ConditionsReader(config) as reader:
                data = export_dataset(reader, config, card)
                outputs.json("coverage.json", {**data["coverage"], "queries": reader.query_metrics})
                outputs.json("dataset.json", data)
            outputs.finish(input_sha256=data["input_sha256"], availability="historical_retrospective")
        elif args.command == "analyze":
            require(args.dataset is not None and card is None, "conditions_analyze_arguments")
            data = load_dataset(args.dataset)
            save_analysis(outputs, analyze(data, config), data)
        else:
            require(args.dataset is not None and card is not None, "conditions_predict_arguments")
            data = load_dataset(args.dataset)
            result = predict_card(data, card, config)
            outputs.json("prediction.json", result)
            outputs.markdown(render_prediction(result))
            outputs.finish(input_sha256=data["input_sha256"], card_sha256=digest(card), availability="reference_only")
        print(json.dumps({"status": "complete", "output": str(outputs.path)}, ensure_ascii=True))
        return 0
    except Exception as error:
        if outputs is not None:
            if reader is not None:
                outputs.json("query-diagnostics.json", reader.query_metrics)
            outputs.fail(error)
        print(json.dumps({"status": "failed", "reason": getattr(error, "reason", "conditions_execution_failed"),
                          "error_type": type(error).__name__}, ensure_ascii=True), file=sys.stderr)
        return error.exit_code if isinstance(error, ResearchError) else 4


if __name__ == "__main__":
    raise SystemExit(main())
