"""概要: spec150の市場残差・内容特徴の固定研究を起動する。
作成日: 2026-10-17
入力: 統合SQLの研究接続設定。引数なし。
出力: 研究runと標準出力。成功0、研究エラーは定義済み終了コード。
実行例: uv run --frozen --extra ml python scripts/run_jra_tipster_residual.py
注意事項: SELECTのみ。旧データ入力・削除・運用変更なし。
"""

import json

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_tipster_residual import execute_residual


def main():
    """固定実験を起動し、秘密を含まない研究エラーだけ表示する。"""
    try:
        print(json.dumps(execute_residual(), ensure_ascii=False))
    except ResearchError as error:
        print(json.dumps({"reason": error.reason, "exit_code": error.exit_code}))
        raise SystemExit(error.exit_code) from None


if __name__ == "__main__":
    main()
