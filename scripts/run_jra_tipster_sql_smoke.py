"""概要: 固定少数日でS06/S08のSQL限定学習・評価・推論を確認する。
作成日: 2026-10-17
入力: 研究専用SQL接続、実装契約095の固定設定。
出力: 新規run、非秘密JSON結果、成功0/失敗理由に対応する終了コード。
実行例: uv run --extra ml python scripts/run_jra_tipster_sql_smoke.py
注意事項: 収益性の本研究ではない。SQLite・旧JSONL・HTTP・NASを入力にしない。
"""

import json
import sys

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_tipster_smoke import execute_smoke


def main() -> int:
    """限定経路確認を実行し秘密を含まない結果だけを表示する。"""
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        print(json.dumps(execute_smoke(), ensure_ascii=False))
        return 0
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}, ensure_ascii=False))
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
