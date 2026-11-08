"""概要: spec120の内容特徴5案比較をSQL入力だけで開始する。
作成日: 2026-10-17
入力: 既存研究reader設定、固定SQL31/34、step4の基準成果物。
出力: 標準出力のrun ID/要約、新規runのモデル・診断・結果。
実行例: uv run --frozen --extra ml python scripts/run_jra_tipster_ablation.py
注意事項: SELECT専用。旧SQLite/JSONL・新規取得・削除・運用変更なし。
"""

import json
from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_tipster_ablation import execute_ablation


if __name__ == "__main__":
    try:
        print(json.dumps(execute_ablation(), ensure_ascii=False), flush=True)
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}), flush=True)
        raise SystemExit(error.exit_code) from None
