"""Feature timing, race symmetry and incomplete O2 protection for V91."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from jra_v91_model import features, fit, forecast, predict


@pytest.fixture
def race():
    path = Path(__file__).resolve().parents[1] / "data/training/jra_o1o2_asof_v1/2024/races.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.loads(next(stream))


def test_prediction_has_no_result_or_t10_dependency(race):
    a = features(race)
    poisoned = deepcopy(race)
    del poisoned["result"]
    del poisoned["source_refs"]
    del poisoned["inputs"]["odds"]["T-10m"]
    for runner in poisoned["inputs"]["runners"]:
        runner["horse_weight"] = 999
        runner["history_features"]["field_size_scaled"] = 999
        runner["history_features"]["horse_no_scaled"] = 999
    b = features(poisoned)
    np.testing.assert_array_equal(a["x"], b["x"])
    model = fit([a], "market", .1)
    assert forecast(model, race) == forecast(model, poisoned)


def test_o2_missing_and_partial_are_neutral(race):
    missing = deepcopy(race)
    missing["inputs"]["odds"]["T-30m"]["quinella"] = None
    partial = deepcopy(race)
    partial["inputs"]["odds"]["T-30m"]["quinella"]["pairs"] = partial["inputs"]["odds"]["T-30m"]["quinella"]["pairs"][:1]
    a, b = features(missing), features(partial)
    assert not a["o2_complete"] and not b["o2_complete"]
    np.testing.assert_array_equal(a["x"], b["x"])
    np.testing.assert_array_equal(a["x"][:, -3:], 0)


def test_runner_permutation_is_invariant(race):
    changed = deepcopy(race)
    changed["inputs"]["runners"].reverse()
    changed["inputs"]["odds"]["T-30m"]["win"]["horses"].reverse()
    a, b = features(race), features(changed)
    assert a["keys"] == b["keys"]
    np.testing.assert_array_equal(a["x"], b["x"])


def test_cancelled_card_number_requires_t30_evidence(race):
    changed = deepcopy(race)
    changed["inputs"]["runners"][0]["horse_no"] = "取消"
    changed["inputs"]["odds"]["T-30m"]["win"]["horses"][0].update(odds=None, status="asterisk_marker")
    f = features(changed)
    assert "1" not in f["keys"] and f["unscored_card_keys"] == ["取消"]
    del changed["inputs"]["odds"]["T-30m"]["win"]["horses"][0]
    with pytest.raises(ValueError, match="incomplete runner market"):
        features(changed)


def test_reject_late_announcement_or_history(race):
    changed = deepcopy(race)
    changed["inputs"]["odds"]["T-30m"]["win"]["announced_at"] = changed["race"]["start_at"]
    with pytest.raises(ValueError, match="after T-30m"):
        features(changed)
    changed = deepcopy(race)
    changed["inputs"]["history_as_of"] = "2024-01-06T12:00:00+09:00"
    with pytest.raises(ValueError, match="history cutoff"):
        features(changed)


def test_race_objective_learns_relative_winner():
    records = [{"keys": ["1", "2"], "market": np.array([.5, .5]),
                "x": np.array([[-1.0], [1.0]]), "target": np.array([0.0, 1.0]),
                "feature_names": ["synthetic"]} for _ in range(20)]
    model = fit(records, "temperature", .1)
    probabilities = predict(model, records[0])
    assert probabilities[1] > .8
    assert probabilities.sum() == pytest.approx(1)
