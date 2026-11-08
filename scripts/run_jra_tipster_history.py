"""概要: S06/S08の内容履歴をSQLだけから読み、既存変換の件数を確認する。
作成日: 2026-10-17
入力: 固定研究設定、研究専用SQL接続、既存の内容変換コード。
出力: 非秘密の件数とSQL入力run。元データを保存しない。
実行例: uv run --extra ml python scripts/run_jra_tipster_history.py
注意事項: 学習・旧JSONL読取・SQLite参照・外部取得・削除は行わない。
"""

import importlib.util
import json
from pathlib import Path
import sys

from jra_srb.jra_research_contracts import ResearchError


def main() -> int:
    """SQL履歴読取と既存純変換を実行し、固定理由だけを出力する。"""
    sys.stdout.reconfigure(encoding="utf-8")
    path = Path(__file__).resolve().parents[1] / ".workstate/jra-srb/tipster-trace-v1/evaluate_chimera.py"
    spec = importlib.util.spec_from_file_location("tipster_history_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        histories, indices, wide, audit = module.load_history()
        print(json.dumps({"status": "passed", "stage": "history_input_only", "overall_complete": False,
                          "identities": len(histories), "indices": len(indices), "wide_races": len(wide),
                          "audit": dict(audit)}, ensure_ascii=False))
        return 0
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}, ensure_ascii=False))
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
