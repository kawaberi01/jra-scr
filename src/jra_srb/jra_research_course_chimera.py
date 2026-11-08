"""概要: D0の教師を競馬場別に限定し、別場への推論を拒否する研究モデル。
作成日: 2026-10-25
入力: 同じ競馬場のD0公開特徴・市場、訓練時だけ正解。
出力: scope付きD0係数と馬連確率。
実行例: uv run --frozen --extra ml python scripts/run_jra_course_chimera.py --help
注意事項: 馬の他場履歴は既存特徴に保持。既定モデルへ自動反映しない。
"""

from . import jra_research_attribute_chimera as base
from .jra_research_r1_live import require

SCOPE = 'spec395-course-only-D0-v1'


def fit(records, course):
    """同じ競馬場だけの教師を検査し、既存D0学習器をそのまま使う。

    Args:
        records: 対象場だけの時系列教師。
        course: JRA競馬場コード1〜10。
    Returns:
        訓練場とscopeを追加した既存D0形式のモデル。
    Raises:
        ResearchError: 空教師・他場混入・無効コード・既存学習器の失敗。
    """
    require(1 <= course <= 10 and bool(records) and all(int(r['course']) == course for r in records), 'course_training_scope')
    fitted = base.fit(records, 'D0')
    fitted.update(training_scope=SCOPE, trained_course=course)
    return fitted


def predict(fitted, record):
    """別場への適用を拒否し、既存D0の結果遮断・日付境界付き推論を使う。"""
    require(fitted.get('training_scope') == SCOPE and fitted.get('trained_course') == int(record['course']), 'course_prediction_scope')
    return base.predict(fitted, record)
