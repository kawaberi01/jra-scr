from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

import jra_srb.app as app_module


def test_model_comparison_passes_actual_wide_market_to_v89(monkeypatch):
    odds = SimpleNamespace()
    bundle = SimpleNamespace(
        race_id="202609200505",
        card=SimpleNamespace(),
        odds_summary=odds,
        meta=SimpleNamespace(component_status={"odds": "available"}),
        fetched_at=datetime(2026, 9, 20, 5, tzinfo=UTC),
    )

    class PredictionService:
        async def get_prediction_bundle(self, *_args, **kwargs):
            assert kwargs["odds_bet_types"] == ["win", "wide"]
            return bundle

    monkeypatch.setattr(
        app_module,
        "build_prediction_record",
        lambda _bundle: {"theory_version": "materials", "prediction_json": {"predicted_ranking": [{"horse_no": "1", "win_odds": 2.0}] }},
    )
    monkeypatch.setattr(
        app_module,
        "load_model_artifact",
        lambda _path: {"trained_through": "2026-09-01", "model_version": "history", "artifact_hash": "test"},
    )
    monkeypatch.setattr(app_module, "build_artifact_live_records", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(app_module, "score_live_records", lambda *_args: [{"horse_no": "1"}])

    def fake_v_theory(*_args, **kwargs):
        assert kwargs["race_odds"] is odds
        return {"status": "available", "model_status": "shadow", "ranking": [{"horse_no": "1"}]}

    monkeypatch.setattr(app_module, "build_v_theory_prediction", fake_v_theory)
    app_module.app.dependency_overrides[app_module.get_jra_prediction_service] = lambda: PredictionService()
    try:
        response = TestClient(app_module.app).get(
            "/jra/meetings/2026-09-20/tokyo/races/5/model-comparison?meeting_no=4&meeting_day=2"
        )
    finally:
        app_module.app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    assert response.json()["v_theory"]["model_status"] == "shadow"
