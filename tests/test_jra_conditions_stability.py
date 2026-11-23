"""概要: 安定化方式の確率境界、過去選択と未来結果遮断を検証する。
作成日: 2026-11-13。
入力: 合成競走・先行計算・pytest。
出力: テストの合否。
実行例: uv run pytest -q tests/test_jra_conditions_stability.py
注意事項: 実DB・外部通信なし。合成結果は性能の証明ではない。
"""

from copy import deepcopy

import pytest

from test_jra_conditions_search import config, data
from jra_srb.jra_conditions_refinement import refine
from jra_srb.jra_conditions_stability import POLICIES, bounded_probabilities, stabilize
from jra_srb.jra_research_contracts import digest


def test_bounded_probability_projection():
    """0〜1、旧確率との差の上限、全馬合計3を同時に守る。"""
    base = [.5]*6
    proposed = [.99, .9, .7, .2, .15, .06]
    for cap in (.05, .1):
        values = bounded_probabilities(proposed, base, cap)
        assert sum(values) == pytest.approx(3)
        assert all(0 <= p <= 1 and abs(p-b) <= cap+1e-12 for p, b in zip(values, base, strict=True))


def test_all_stability_policies_preserve_sum_and_selection_dates(config):
    """8方式と2基準を同じ年に予測し、選択日と確率総和を検査する。"""
    value = data()
    source = refine(value, config, repeats=5)
    result = stabilize(source, value, repeats=5)
    assert len(result["predictions"]) == len(POLICIES)*2
    for prediction in result["predictions"]:
        assert sum(r["probability_top3"] for r in prediction["runners"]) == pytest.approx(3)
        assert prediction["selection_latest_date"] < prediction["race_date"]


def test_stability_future_result_not_used_in_earlier_prediction(config):
    """最後の評価年の結果変更は、その年の事前予測と構成選択を変えない。"""
    value = data()
    before = stabilize(refine(value, config, repeats=5), value, repeats=5)
    changed = deepcopy(value)
    for row in changed["races"][-1]["runners"]:
        row["rank"] = 7-row["rank"]
    changed.pop("input_sha256")
    changed["input_sha256"] = digest(changed)
    after = stabilize(refine(changed, config, repeats=5), changed, repeats=5)
    assert before["predictions"] == after["predictions"]
