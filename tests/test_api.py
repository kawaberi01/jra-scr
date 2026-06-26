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


def test_get_race_odds_by_meeting_coordinates_for_expanded_bet_types_endpoint():
    service = JraService(provider=FixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get(
            "/meetings/2026-03-22/nakayama/races/11/odds?bet_type=wide&combination=4,10"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["bet_type"] == "wide"
        assert len(body["entries"]) == 1
        assert body["entries"][0]["combination"] == ["4", "10"]
        assert body["entries"][0]["odds"] == "16.1"
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


def test_mcp_endpoint_is_mounted():
    client = TestClient(app)
    response = client.get("/mcp")
    assert response.status_code != 404


def test_openapi_contains_japanese_api_guidance():
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    body = response.json()

    assert body["info"]["title"] == "JRA レース情報 API"
    assert "Swagger UI" in body["info"]["description"]

    meeting_get = body["paths"]["/meetings/{date_}/{course}"]["get"]
    assert meeting_get["summary"] == "開催一覧を取得"
    assert meeting_get["tags"] == ["meetings"]

    odds_get = body["paths"]["/meetings/{date_}/{course}/races/{race_no}/odds"]["get"]
    assert odds_get["summary"] == "開催日・開催地・レース番号でオッズを取得"
    parameters = {item["name"]: item for item in odds_get["parameters"]}
    assert parameters["bet_type"]["description"] == "券種コード。例: win, quinella, exacta, wide, trio, trifecta"
    assert parameters["combination"]["description"] == "組み合わせをカンマ区切りで指定します。例: 10,11 または 4,10,11"
