from fastapi.testclient import TestClient

from jra_srb.app import app, get_service
from jra_srb.provider import FixtureProvider
from jra_srb.service import JraService


def test_get_race_card_endpoint():
    service = JraService(provider=FixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get("/races/202603220101/card")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "202603220101"
        assert body["race_name"] == "若葉ステークス"
        assert len(body["runners"]) == 2
    finally:
        app.dependency_overrides.clear()


def test_get_meeting_endpoint():
    service = JraService(provider=FixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get("/meetings/2026-03-22/nakayama")
        assert response.status_code == 200
        body = response.json()
        assert body["course"] == "nakayama"
        assert len(body["races"]) == 12
        assert body["races"][10]["race_id"] == "202603220611"
    finally:
        app.dependency_overrides.clear()


def test_get_race_card_by_meeting_coordinates_endpoint():
    service = JraService(provider=FixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get("/meetings/2026-03-22/nakayama/races/11/card")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "202603220611"
        assert body["race_name"] == "千葉ステークス"
        assert len(body["runners"]) == 16
    finally:
        app.dependency_overrides.clear()


def test_get_race_odds_by_meeting_coordinates_endpoint():
    service = JraService(provider=FixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get(
            "/meetings/2026-03-22/nakayama/races/11/odds?bet_type=trifecta&combination=1,2,3"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["bet_type"] == "trifecta"
        assert len(body["entries"]) == 1
        assert body["entries"][0]["combination"] == ["1", "2", "3"]
    finally:
        app.dependency_overrides.clear()


def test_get_race_result_by_meeting_coordinates_endpoint():
    service = JraService(provider=FixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get("/meetings/2026-03-22/nakayama/races/11/result")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "202603220611"
        assert body["race_name"] == "千葉ステークス"
        assert body["results"][0]["horse_name"] == "ドラゴンウェルズ"
        assert any(p["bet_type"] == "3連単" for p in body["payouts"])
    finally:
        app.dependency_overrides.clear()
