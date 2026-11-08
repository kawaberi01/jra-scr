"""概要: 固定6案の予想家由来SQL研究を開始する専用CLI。
作成日: 2026-10-17
入力: 研究reader接続、spec100の固定条件。
出力: 標準出力にrun ID・要約、新規runにモデル・予測・評価。
実行例: uv run --frozen --extra ml python scripts/run_jra_tipster_experiment.py
注意事項: SELECTのみ。既使用期間の研究であり運用モデルを置換しない。
"""

import json
from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_tipster_experiment import execute_experiment


if __name__ == "__main__":
    try:
        print(json.dumps(execute_experiment(), ensure_ascii=False), flush=True)
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}), flush=True)
        raise SystemExit(error.exit_code) from None
