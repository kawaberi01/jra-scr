from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys

import numpy as np
import pytest
from scipy.special import softmax

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from jra_second_ten_model import (prepare, latent_support, ranking_stages, chronological_calibration_split,
                                  fit_choice, choice, fit_boost, boost_delta, fit_settlement, score_suite)
from jra_ten_trials_model import pair_probability


@pytest.fixture
def race():
    path = Path(__file__).resolve().parents[1] / "data/training/jra_o1o2_asof_v1/2024/races.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.loads(next(stream))


def test_all_new_features_ignore_result_and_later_odds(race):
    before = prepare(race)
    altered = deepcopy(race)
    del altered["result"]
    del altered["inputs"]["odds"]["T-10m"]
    for runner in altered["inputs"]["runners"]:
        runner["horse_weight"] = 999
        runner["history_features"]["field_size_scaled"] = 999
        runner["history_features"]["horse_no_scaled"] = 999
    after = prepare(altered)
    for feature in ("enriched", "latent", "boost_x", "latent_probability"):
        np.testing.assert_array_equal(before[feature], after[feature])


def test_latent_support_recovers_synthetic_strength():
    expected = np.array([.5, .3, .2])
    indices = [(0, 1), (0, 2), (1, 2)]
    record = {"keys": ["1", "2", "3"], "market": np.full(3, 1/3),
              "pair": {"indices": indices, "market": pair_probability(expected, indices)}}
    np.testing.assert_allclose(latent_support(record), expected, atol=.001)
    record["pair"] = None
    np.testing.assert_array_equal(latent_support(record), record["market"])


def test_ranking_stages_remove_preceding_finishers():
    r = {"keys": ["1", "2", "3"], "market": np.array([.4, .4, .2]),
         "enriched": np.array([[1.], [2.], [3.]]), "training_ranks": np.array([2, 1, 3])}
    stages, weights = ranking_stages([r])
    assert len(stages) == 2
    np.testing.assert_array_equal(stages[0]["target"], [0, 1, 0])
    assert stages[1]["keys"] == ["1", "3"]
    np.testing.assert_array_equal(stages[1]["target"], [1, 0])
    assert sum(weights) == pytest.approx(1)


def test_calibration_split_never_divides_one_day():
    records = [{"race_date": f"2025-01-{day:02d}"} for day in range(1, 9) for _ in range(3)]
    earlier, later, boundary = chronological_calibration_split(records)
    assert max(r["race_date"] for r in earlier) < min(r["race_date"] for r in later)
    assert boundary == "2025-01-07"


def test_choice_and_boost_learn_a_race_relative_signal():
    records = [{"keys": ["1", "2"], "market": np.array([.5, .5]), "target": np.array([0., 1.]),
                "enriched": np.array([[-1.], [1.]]), "boost_x": np.array([[-1.], [1.]])} for _ in range(200)]
    linear = fit_choice(records)
    assert choice(linear, records[0])[1] > .8
    boosted = fit_boost(records, rounds=10)
    p = softmax(np.log(records[0]["market"]) + boost_delta(boosted, records[0]))
    assert p[1] > .6 and p.sum() == pytest.approx(1)


def test_settlement_shrinkage_does_not_assume_improving_prices():
    r = {"price": np.array([2., 4.]), "payout": np.array([0, 200]), "surface": "dirt"}
    model = fit_settlement([r])
    assert model["ratios"][1] == pytest.approx(30.5/31)
    assert model["ratios"].max() <= 1


def test_summer_refused_before_model_access():
    with pytest.raises(ValueError, match="summer"):
        score_suite({"excluded_months": [6, 7, 8]}, {"race_date": "2026-08-01"})
