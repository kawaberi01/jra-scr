"""概要: spec160の市場残差・非線形木比較を起動する。
作成日: 2026-10-17
入力: --baseline-runで指定したspec150の完了run、統合SQL接続設定。
出力: 新規研究runと標準出力。成功0、研究エラーは定義済み終了コード。
実行例: uv run --frozen --extra ml python scripts/run_jra_tipster_boost.py --baseline-run <run-id>
注意事項: 旧モデル上書き・原データ複製・削除・運用変更なし。
"""

import argparse
import json

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_tipster_boost import execute_boost


def main():
    """基準runを受け取り、固定した木比較を実行する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-run", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(execute_boost(args.baseline_run), ensure_ascii=False))
    except ResearchError as error:
        print(json.dumps({"reason": error.reason, "exit_code": error.exit_code}))
        raise SystemExit(error.exit_code) from None


if __name__ == "__main__":
    main()
