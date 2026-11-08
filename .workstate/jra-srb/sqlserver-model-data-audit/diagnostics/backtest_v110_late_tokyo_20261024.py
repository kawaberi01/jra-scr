"""概要: 既存のV110月次検証を再利用し2024/2025の同一v2検証を実行する。
作成日: 2026-10-24
入力: spec340、保存v2の2020〜2025、既存の元V110関数。
出力: artifacts/jra_research/v110_late_tokyo_20261024の月別モデル・予測・集計。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/backtest_v110_late_tokyo_20261024.py
注意事項: 外部通信・SQL・実購入なし。旧18fitは再実行しない。新規出力先のみ使用。
"""

from pathlib import Path

import backtest_v110_early_tokyo_20261023 as existing


def main():
    """仕様と評価年だけを固定上書きして既存実行関数へ委譲する。"""
    existing.SPEC = Path(__file__).resolve().parents[1]/'spec/340-V110の追加年代検証と採否の終了基準.md'
    existing.EVALUATION_YEARS = (2024, 2025)
    existing.MONTHS = [f'{y}-{m:02d}' for y in existing.EVALUATION_YEARS
                       for m in range(1, 13) if m not in (6, 7, 8)]
    existing.run(Path('artifacts/jra_research/v110_late_tokyo_20261024'))


if __name__ == '__main__':
    main()
