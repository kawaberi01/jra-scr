"""概要: 20仮説研究の事前入力判定を起動する。
作成日: 2026-10-18
入力: --preflight-only、固定SQLの原文/T30/HR。
出力: 新規runとJSON結果。正常な入力不足は0、実行異常は固定コード。
実行例: uv run --frozen --extra ml python scripts/run_jra_chimera_twenty.py --preflight-only
注意事項: 入力未達時は学習前停止。既定変更・実購入なし。
"""

import argparse
import json

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_chimera_twenty import execute_preflight


def main():
    """承認済みの事前判定を起動し、秘密情報を含まないエラーを表示する。"""
    parser = argparse.ArgumentParser(description="新キメラ20仮説の入力事前判定")
    parser.add_argument("--preflight-only", action="store_true", required=True)
    parser.parse_args()
    try:
        print(json.dumps(execute_preflight(), ensure_ascii=False))
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}, ensure_ascii=False))
        raise SystemExit(error.exit_code) from None


if __name__ == "__main__":
    main()
