"""概要: 20仮説の性能測定と選抜/停止を保存成果物から再集計する。
作成日: 2026-10-18
入力: --run-id、当該runの集計/モデル/予測/hash。
出力: verification.jsonとJSON結果。成功0、不整合は固定コード。
実行例: uv run --frozen --extra ml python scripts/verify_jra_chimera_twenty_fit.py --run-id RUN_ID
注意事項: SQLアクセス・再学習・既定変更なし。
"""

import argparse
import json

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_chimera_twenty_fit import verify


def main():
    """一意runの保存後検証を起動し、確認件数と停止の整合を表示する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.run_id), ensure_ascii=False))
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}, ensure_ascii=False))
        raise SystemExit(error.exit_code) from None


if __name__ == "__main__":
    main()
