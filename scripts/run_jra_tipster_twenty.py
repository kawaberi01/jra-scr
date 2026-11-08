"""概要: SQL保存の2003年以降データを使う理論20回研究を開始する。
作成日: 2026-10-17
入力: spec140、研究reader設定、固定SQL4〜27/31と既存評価集合。
出力: 新規runのモデル・20件台帳・評価・入力診断、標準出力。
実行例: uv run --frozen --extra ml python scripts/run_jra_tipster_twenty.py
注意事項: SELECTのみ。既参照期間の研究で、元データや運用を変更しない。
"""

import json
import argparse
from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_tipster_twenty import execute_twenty


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reuse-trained-run", help="校正・評価の是正時に学習済みモデルを再利用するrun ID")
    args = parser.parse_args()
    try:
        print(json.dumps(execute_twenty(args.reuse_trained_run), ensure_ascii=False), flush=True)
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}), flush=True)
        raise SystemExit(error.exit_code) from None
