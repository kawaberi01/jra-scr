"""概要: spec180のR1確率校正・価格研究を固定条件で起動する。
作成日: 2026-10-18
入力: 統合SQL研究reader設定と保存済みR1。CLI引数なし。
出力: 新規研究runと標準出力。正常0、異常は固定研究終了コード。
実行例: uv run --frozen --extra ml python scripts/run_jra_r1_calibration.py
注意事項: 元R1の再学習・デフォルト変更・外部API送信なし。SQL SELECTのみ。
"""

import json

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_r1_calibration import execute


def main():
    """固定研究の結果か、秘密を含まない失敗コードを出力する。"""
    try:
        print(json.dumps(execute(), ensure_ascii=False))
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}, ensure_ascii=False))
        raise SystemExit(error.exit_code) from None


if __name__ == "__main__":
    main()
