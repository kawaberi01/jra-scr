"""概要: 継続仮説の候補数、初版との一致、加重集計、時点境界と採用基準を検査する。
作成日: 2026-11-13。
入力: 合成競走と既存設定、pytest。
出力: テストの合否。
実行例: uv run pytest -q tests/test_jra_conditions_refinement.py
注意事項: 実DB/外部通信なし。合成結果は有効性の証明ではない。
"""

from collections import Counter
from copy import deepcopy

import pytest

from test_jra_conditions_search import config, data
from jra_srb.jra_conditions_refinement import (
    BASELINE, candidate_prediction, group_deltas, qualify, refine, refinement_candidates,
)
from jra_srb.jra_race_conditions import examples, predict
from jra_srb.jra_research_contracts import digest


def test_candidate_counts(config):
    """事前に固定した69候補と各仮説の内訳を確認する。"""
    candidates = refinement_candidates(config)
    assert len(candidates) == 69
    assert Counter(c["family"] for c in candidates) == {"H1": 6, "H2": 30, "H3": 18, "H4": 6, "H5": 6, "H6": 3}


def test_baseline_equivalence_and_uniform(config):
    """無減衰・縮約20・等配分は初版を再現し、倍率0は一律になる。"""
    races = examples(data())
    c = next(c for c in refinement_candidates(config) if c["pattern"] == BASELINE)
    deltas = group_deltas(races[:5], races[5], config, c)
    new = candidate_prediction(deltas, races[5], c)
    old = predict(races[:5], races[5], config)
    assert {r["horse_no"]: r["probability_top3"] for r in new["runners"]} == pytest.approx(
        {r["horse_no"]: r["probability_top3"] for r in old["runners"]})
    zero = candidate_prediction(deltas, races[5], {**c, "scale": 0})
    assert all(r["probability_top3"] == pytest.approx(.5) for r in zero["runners"])


def test_subset_normalization(config):
    """1群だけの正規化は、5群平均を使う時の5倍の強度になる。"""
    races = examples(data())
    candidates = refinement_candidates(config)
    c = next(c for c in candidates if c["pattern"] == BASELINE)
    deltas = group_deltas(races[:5], races[5], config, c)
    selected = next(c for c in candidates if c["pattern"] == "H2-P01")
    left = candidate_prediction(deltas, races[5], selected)
    isolated = [{**r, "deltas": [r["deltas"][0], 0, 0, 0, 0]} for r in deltas]
    right = candidate_prediction(isolated, races[5], {**c, "scale": 5})
    assert [r["probability_top3"] for r in left["runners"]] == pytest.approx([r["probability_top3"] for r in right["runners"]])


def test_weighted_evidence_and_future_isolation(config):
    """半減期の有効件数と、当該・未来を集計しない境界を確認する。"""
    races = examples(data())
    c = next(c for c in refinement_candidates(config) if c["pattern"] == "H5-T5-S1")
    result = group_deltas(races[:5], races[5], config, c)
    item = result[0]["evidence"][0]["items"][0]
    assert item["n"] == 15
    assert item["weighted_n"] == pytest.approx(3 * sum(2**(-gap/5) for gap in range(1, 6)))
    assert result == group_deltas(races, races[5], config, c)


def test_nested_future_and_threshold(config):
    """69候補の選択は当該以後の結果に依存せず、全7範囲で5年を待つ。"""
    before = refine(data(), config, repeats=10)
    assert len(before["annual"]) == 69 * 7
    assert len(before["selection"]) == 7 * 2
    changed = deepcopy(data())
    for race in changed["races"][-2:]:
        for row in race["runners"]:
            row["rank"] = 7-row["rank"]
    changed.pop("input_sha256")
    changed["input_sha256"] = digest(changed)
    after = refine(changed, config, repeats=10)
    for scope in before["outer"]:
        left = next(r for r in before["selection"] if r["scope"] == scope)
        right = next(r for r in after["selection"] if r["scope"] == scope)
        assert left["pattern"] == right["pattern"]
        assert left["candidate_brier"] == right["candidate_brier"]
        assert left["selection_latest_date"] < left["race_date"]
    assert [p for p in before["predictions"] if p["race_date"] <= "2013-11-15"] == [p for p in after["predictions"] if p["race_date"] <= "2013-11-15"]


def test_qualification_requires_all_four_conditions():
    """改善率・区間・別損失・改善開催数の一つでも未達なら採用しない。"""
    base = {"brier": .15, "logloss": .5}
    good = {"brier": .14, "logloss": .49, "races": 13}
    interval = {"interval95": [-.02, -.001]}
    assert qualify(good, base, interval, 7)
    assert not qualify({**good, "brier": .149}, base, interval, 7)
    assert not qualify({**good, "logloss": .51}, base, interval, 7)
    assert not qualify(good, base, {"interval95": [-.02, .001]}, 7)
    assert not qualify(good, base, interval, 6)
