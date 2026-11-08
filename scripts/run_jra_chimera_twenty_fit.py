"""概要: 承認済み20仮説の固定学習・時系列選抜・性能測定を起動する。
作成日: 2026-10-18
入力: spec230〜232、入力事前判定run。引数なし。
出力: 新規研究run、JSON結果。性能未達0、実装/入力異常は固定コード。
実行例: uv run --frozen --extra ml python scripts/run_jra_chimera_twenty_fit.py
注意事項: 候補追加・閾値調整・既定変更・実購入なし。
"""

import json

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_chimera_twenty_fit import execute


def main():
    """固定研究を起動し、実装異常を性能不合格と区別する。"""
    try:
        print(json.dumps(execute(), ensure_ascii=False))
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}, ensure_ascii=False))
        raise SystemExit(error.exit_code) from None


if __name__ == "__main__":
    main()
