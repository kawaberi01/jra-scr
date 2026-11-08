"""概要: 20仮説研究の入力事前判定を保存成果物だけから再集計する。
作成日: 2026-10-18
入力: --run-id、対象runのJSON/hash。
出力: verification.jsonとJSON結果。成功0、不一致は固定エラーコード。
実行例: uv run --frozen --extra ml python scripts/verify_jra_chimera_twenty.py --run-id RUN_ID
注意事項: SQLアクセス・再学習なし。元runのモデルや予測は変更しない。
"""

import argparse
import json

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_chimera_twenty import verify_preflight


def main():
    """run IDを検査し、保存採否の独立再集計を実行する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(verify_preflight(args.run_id), ensure_ascii=False))
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}, ensure_ascii=False))
        raise SystemExit(error.exit_code) from None


if __name__ == "__main__":
    main()
