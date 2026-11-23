"""概要: 条件群の外れ値抑制と旧平均の意味を検証する。
作成日: 2026-11-13。
入力: 5群の合成差分、pytest。
出力: 合否。
実行例: uv run pytest -q tests/test_jra_conditions_robust.py
注意事項: 外部通信・DBなし。
"""

import importlib.util
from pathlib import Path
import sys

import pytest


def test_robust_aggregation_excludes_single_outlier():
    """中央値と中央3群平均が一つの極端な群で変わらず、通常平均は変わる。"""
    scripts = Path(__file__).resolve().parents[1]/"scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location("robust_cli_test", scripts/"run_jra_conditions_robust.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        values = [0., .1, .2, .3, 100.]
        assert module.robust_delta(values, "median") == .2
        assert module.robust_delta(values, "trimmed") == pytest.approx(.2)
        assert module.robust_delta(values, "mean") > 20
    finally:
        sys.path.remove(str(scripts))
