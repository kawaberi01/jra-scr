"""概要: 終了基準を固定したR1のT10比較1案を起動する。
作成日: 2026-10-18
入力: 保存R1・spec180成果物・統合SQL研究reader。引数なし。
出力: 新規runの合否と研究終了判断。正常0、実装/入力異常は固定コード。
実行例: uv run --frozen --extra ml python scripts/run_jra_r1_timing.py
注意事項: 性能未達は正常な研究結果として系列を終了する。再学習・既定変更なし。
"""

import json

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_r1_timing import execute


def main():
    """固定比較を実行し、結果と実装失敗を区別して表示する。"""
    try:
        print(json.dumps(execute(), ensure_ascii=False))
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}, ensure_ascii=False))
        raise SystemExit(error.exit_code) from None


if __name__ == "__main__":
    main()
