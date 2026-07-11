import pytest

from jra_srb.jra_history_dataset import FEATURE_NAMES
from jra_srb.jra_history_model import predict_with_artifact, train_history_models


def test_predict_with_json_artifact_needs_no_sklearn_runtime():
    count = len(FEATURE_NAMES)
    artifact = {
        "feature_names": FEATURE_NAMES,
        "scaler": {"mean": [0.0] * count, "scale": [1.0] * count},
        "models": {
            "win": {"intercept": 0.0, "coefficients": [0.0] * count},
            "top3": {"intercept": 0.0, "coefficients": [0.0] * count},
        },
    }
    result = predict_with_artifact(artifact, [0.0] * count)
    assert result == {"win_probability": 0.5, "top3_probability": 0.5}


def test_training_uses_chronological_date_holdout():
    pytest.importorskip("sklearn")
    records = []
    for day in range(1, 13):
        for horse in range(1, 7):
            features = [0.0] * len(FEATURE_NAMES)
            features[0] = horse / 6
            features[1] = day / 12
            records.append({
                "race_id": f"202401{day:02d}06{day:02d}",
                "race_date": f"2024-01-{day:02d}",
                "horse_no": str(horse), "features": features,
                "label_win": int(horse == 1), "label_top3": int(horse <= 3),
            })
    artifact, report = train_history_models(records, validation_fraction=0.25)
    assert report["split"]["cutoff_date"] == "2024-01-10"
    assert report["split"]["train_dates"] == 9
    assert report["split"]["validation_dates"] == 3
    assert artifact["odds_used"] is False
    assert artifact["training_races"] == 12
