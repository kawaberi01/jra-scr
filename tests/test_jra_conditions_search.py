"""概要: 全32構成と選択時点の境界、順位同率、初版との整合を検証する。
作成日: 2026-11-13。
入力: 合成競走、固定設定、pytest。
出力: 対象テストの合否。
実行例: uv run pytest -q tests/test_jra_conditions_search.py
注意事項: 実DB・外部通信なし。合成成績は実競馬の有効性を示さない。
"""

from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from jra_srb.jra_conditions_search import (
    bootstrap_difference, choose_pattern, inspect_subsets, patterns, score_prediction, subset_prediction,
)
from jra_srb.jra_race_conditions import examples, load_config, predict
from jra_srb.jra_research_contracts import ResearchError, digest


@pytest.fixture
def config():
    """初版と共通の設定を読む。"""
    return load_config(Path(__file__).resolve().parents[1] / "configs/research/race_conditions_elizabeth_v1.json")


def data():
    """12開催の事前属性と結果を持つ小さな合成入力を作る。"""
    races = []
    for year in range(2003, 2015):
        races.append({"race_key": f"{year}11150811", "race_date": f"{year}-11-15", "race_name": "エリザベス女王杯",
                      "venue_code": "08", "distance": 2200, "track_code": "18", "conditions": {},
                      "runners": [{"horse_id": f"200000000{i}", "horse_name": f"馬{i}", "horse_no": f"{i:02d}",
                                   "age": 3 if i <= 3 else 5, "sex": "2", "frame_no": i,
                                   "weight_carried": 56., "status": "active", "rank": i} for i in range(1, 7)]})
    result = {"schema_version": 1, "race_name": "エリザベス女王杯", "races": races, "history": []}
    result["input_sha256"] = digest(result)
    return result


def test_all_32_and_group_count(config):
    """全32構成を重複なく列挙し、群数ごとの構成数を検査する。"""
    p = patterns(config)
    assert len({tuple(v["groups"]) for v in p}) == 32
    assert Counter(v["group_count"] for v in p) == {0: 1, 1: 5, 2: 10, 3: 10, 4: 5, 5: 1}


@pytest.mark.parametrize("disabled", [None, *range(5)])
def test_reproduce_full_and_previous_ablations(config, disabled):
    """全群および各1群除去の全馬確率が初版の算式に一致する。"""
    rows = examples(data())
    full = predict(rows[:5], rows[5], config)
    groups = list(config["groups"])
    original = predict(rows[:5], rows[5], config, None if disabled is None else groups[disabled])
    mask = 31 if disabled is None else 31 ^ (1 << disabled)
    result = subset_prediction(full, patterns(config)[mask])
    assert {r["horse_no"]: r["probability_top3"] for r in result["runners"]} == pytest.approx(
        {r["horse_no"]: r["probability_top3"] for r in original["runners"]}, abs=1e-12)


def test_uniform_and_partial_boundary_ties():
    """一律と上位3頭境界の同率で、馬番による見かけの技能を作らない。"""
    target = {"rows": [{"horse_no": str(i), "outcome": {"top3": i <= 3}} for i in range(1, 7)]}
    uniform = {"runners": [{"horse_no": str(i), "probability_top3": .5} for i in range(1, 7)]}
    metric = score_prediction(uniform, target)
    assert metric["top1_top3_hit"] == .5 and metric["top3_captured"] == 1.5
    partial = {"runners": [{"horse_no": str(i), "probability_top3": p}
                            for i, p in enumerate([.8, .5, .5, .5, .4, .3], 1)]}
    assert score_prediction(partial, target)["top3_captured"] == pytest.approx(1 + 4/3)


def test_nested_selection_wait_and_future_result_isolation(config):
    """選択用5開催を待ち、当該・未来の結果を構成選択や以前の予想に混ぜない。"""
    before = inspect_subsets(data(), config, bootstrap_repeats=30)
    assert len(before["annual"]) == 32 * 7
    assert len(before["selection"]) == 2
    first = before["selection"][0]
    assert first["race_date"] == "2013-11-15" and first["selection_races"] == 5
    assert first["selection_latest_date"] < first["race_date"]
    altered = data()
    for race in altered["races"][-2:]:
        for r in race["runners"]:
            r["rank"] = 7 - r["rank"]
    altered.pop("input_sha256")
    altered["input_sha256"] = digest(altered)
    after = inspect_subsets(altered, config, bootstrap_repeats=30)
    for key in ("pattern", "chosen_groups", "selection_brier", "candidate_brier"):
        assert first[key] == after["selection"][0][key]
    day = first["race_date"]
    assert [p for p in before["predictions"] if p["race_date"] <= day] == [p for p in after["predictions"] if p["race_date"] <= day]


def test_selection_tie_prefers_fewer_groups(config):
    """主指標が同じなら結果の別指標で選び直さず、最小群数にする。"""
    annual = [{"pattern": p["pattern"], "races": 1, "runners": 6, "brier": .25, "logloss": .7,
               "top1_top3_hit": 1 if p["mask"] else 0, "top3_captured": 1} for p in patterns(config)]
    assert choose_pattern(annual, patterns(config))["mask"] == 0


def test_bootstrap_pairing_and_determinism():
    """開催単位の対と固定seedを守り、異なる対象年の比較を拒否する。"""
    first = [{"race_key": str(i), "races": 1, "runners": 6+i, "brier": .2, "logloss": .6,
              "top1_top3_hit": .5, "top3_captured": 1.5} for i in range(3)]
    second = [{**r, "brier": .25} for r in first]
    value = bootstrap_difference(first, second, repeats=50)
    assert value == bootstrap_difference(first, second, repeats=50)
    assert value["difference"] == pytest.approx(-.05)
    second.reverse()
    with pytest.raises(ResearchError, match="pairing"):
        bootstrap_difference(first, second, repeats=50)


def test_tampered_dataset_rejected(config):
    """内容SHAが違う入力で比較を実行しない。"""
    value = deepcopy(data())
    value["races"][0]["runners"][0]["age"] = 4
    with pytest.raises(ResearchError, match="dataset_sha"):
        inspect_subsets(value, config)
