from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from jra_ten_trials_model import direct_pair_design, group_mask, pair_probability, pick_ticket, prepare, score_suite
from evaluate_jra_ten_trials import gate, summarize, windows


@pytest.fixture
def race():
    path = Path(__file__).resolve().parents[1] / "data/training/jra_o1o2_asof_v1/2024/races.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.loads(next(stream))


def test_features_do_not_use_results_or_t10(race):
    expected = prepare(race)
    poisoned = deepcopy(race)
    poisoned.pop("result")
    poisoned.pop("source_refs")
    poisoned["inputs"]["odds"].pop("T-10m")
    actual = prepare(poisoned)
    np.testing.assert_array_equal(expected["ml"], actual["ml"])
    np.testing.assert_array_equal(direct_pair_design(expected), direct_pair_design(actual))


def test_pair_probability_and_symmetric_design(race):
    r = prepare(race)
    q = r["pair"]
    p = pair_probability(r["market"], q["indices"])
    assert p.sum() == pytest.approx(1)
    swapped = deepcopy(r)
    swapped["pair"]["indices"] = [(j, i) for i, j in q["indices"]]
    np.testing.assert_allclose(p, pair_probability(r["market"], swapped["pair"]["indices"]))
    np.testing.assert_allclose(direct_pair_design(r), direct_pair_design(swapped), atol=1e-12)


def test_summer_is_rejected_before_scoring():
    with pytest.raises(ValueError, match="summer"):
        score_suite({"excluded_months": [6, 7, 8]}, {"race_date": "2026-07-01"})


def test_time_windows_are_strict_and_no_same_day_training():
    records = [{"race_date": d} for d in ("2025-12-31", "2026-01-01", "2026-03-31", "2026-04-01")]
    _, _, train, test = windows(records, (("2026-01-01", "2026-03-31"),))[0]
    assert [r["race_date"] for r in train] == ["2025-12-31"]
    assert len(test) == 2


def test_ticket_choice_obeys_band_group_and_one_ticket():
    r = {"keys": ["1", "2", "3"], "price": np.array([1.5, 4., 10.]),
         "popularity": np.array([1, 2, 3]), "surface": "dirt", "distance": 1200}
    s = {"probability": np.array([.4, .3, .3]), "projected_return": np.array([4., 1.2, 1.3])}
    ticket = pick_ticket(r, s, "win", {"group": "favorite", "threshold": 1.1})
    assert ticket["key"] == "3"
    assert pick_ticket(r, s, "win", {"group": "turf", "threshold": 1.1}) is None
    assert group_mask(r, "sprint").all()


def test_profit_gate_requires_breadth_and_outlier_robustness():
    rows = [{"race_id": str(i), "race_date": "2026-01-01", "loss": 1.,
             "ticket": {"payout": 10000 if i == 0 else 0}} for i in range(10)]
    s = summarize(rows, bootstrap=False)
    assert s["roi"] == 10
    assert s["roi_without_top3"] == 0
    assert s["max_drawdown_yen"] == 900
    assert not gate(s, {"fold": s}, "development")["passed"]
