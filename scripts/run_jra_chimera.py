"""概要: 固定キメラA/AB/ABCの学習と性能ゲートを起動する。
作成日: 2026-10-18
入力: spec226、固定SQL原文、保存R1とデータ監査。引数なし。
出力: 新規研究runと標準出力。成功0、入力/実装異常は固定コード。
実行例: uv run --frozen --extra ml python scripts/run_jra_chimera.py
注意事項: 3構成固定。開発未達なら後続評価しない。既定変更なし。
"""

import json

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_chimera import execute


def main():
    """性能不合格を正常な研究結果として、実装/入力異常と分離して表示する。"""
    try:
        print(json.dumps(execute(), ensure_ascii=False))
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}, ensure_ascii=False))
        raise SystemExit(error.exit_code) from None


if __name__ == "__main__":
    main()
