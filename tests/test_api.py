from fastapi.testclient import TestClient

from jra_srb.app import app, get_service
from jra_srb.errors import BadRequestError, ResourceNotFoundError
from jra_srb.provider import FixtureProvider, ProviderError
from jra_srb.service import JraService


WAKABA_STAKES = "\u82e5\u8449\u30b9\u30c6\u30fc\u30af\u30b9"
CHIBA_STAKES = "\u5343\u8449\u30b9\u30c6\u30fc\u30af\u30b9"
DRAGON_WELLS = "\u30c9\u30e9\u30b4\u30f3\u30a6\u30a7\u30eb\u30ba"
TRIFECTA_LABEL = "3\u9023\u5358"
API_TITLE = "JRA \u30ec\u30fc\u30b9\u60c5\u5831 API"
MEETING_SUMMARY = "\u958b\u50ac\u4e00\u89a7\u3092\u53d6\u5f97"
MEETING_ODDS_SUMMARY = "\u958b\u50ac\u65e5\u30fb\u958b\u50ac\u5730\u30fb\u30ec\u30fc\u30b9\u756a\u53f7\u3067\u30aa\u30c3\u30ba\u3092\u53d6\u5f97"
BET_TYPE_DESCRIPTION = "\u5238\u7a2e\u30b3\u30fc\u30c9\u3002\u4f8b: win, quinella, exacta, wide, trio, trifecta"
COMBINATION_DESCRIPTION = "\u7d44\u307f\u5408\u308f\u305b\u3092\u30ab\u30f3\u30de\u533a\u5207\u308a\u3067\u6307\u5b9a\u3057\u307e\u3059\u3002\u4f8b: 10,11 \u307e\u305f\u306f 4,10,11"


def test_get_race_card_endpoint():
    service = JraService(provider=FixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get("/races/202603220101/card")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "202603220101"
        assert body["race_name"] == WAKABA_STAKES
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
        assert body["race_name"] == CHIBA_STAKES
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
        assert body["race_name"] == CHIBA_STAKES
        assert body["results"][0]["horse_name"] == DRAGON_WELLS
        assert any(p["bet_type"] == TRIFECTA_LABEL for p in body["payouts"])
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

    assert body["info"]["title"] == API_TITLE
    assert "Swagger UI" in body["info"]["description"]

    meeting_get = body["paths"]["/meetings/{date_}/{course}"]["get"]
    assert meeting_get["summary"] == MEETING_SUMMARY
    assert meeting_get["tags"] == ["meetings"]

    odds_get = body["paths"]["/meetings/{date_}/{course}/races/{race_no}/odds"]["get"]
    assert odds_get["summary"] == MEETING_ODDS_SUMMARY
    parameters = {item["name"]: item for item in odds_get["parameters"]}
    assert parameters["bet_type"]["description"] == BET_TYPE_DESCRIPTION
    assert parameters["combination"]["description"] == COMBINATION_DESCRIPTION


class MissingRaceService:
    async def get_race_card(self, race_id: str):
        raise ResourceNotFoundError(f"race not found for race_id={race_id}")


class UnsupportedBetTypeService:
    async def get_race_odds(self, race_id: str, **kwargs):
        raise BadRequestError("unsupported bet_type=foobar")


class BrokenUpstreamService:
    async def get_meeting(self, target_date, course: str):
        raise ProviderError("failed to fetch https://www.jra.go.jp/JRADB/accessD.html: HTTP 503")


def test_not_found_error_is_returned_as_404():
    app.dependency_overrides[get_service] = lambda: MissingRaceService()
    try:
        client = TestClient(app)
        response = client.get("/races/202603220101/card")
        assert response.status_code == 404
        assert response.json() == {"detail": "race not found for race_id=202603220101"}
    finally:
        app.dependency_overrides.clear()


def test_bad_request_error_is_returned_as_400():
    app.dependency_overrides[get_service] = lambda: UnsupportedBetTypeService()
    try:
        client = TestClient(app)
        response = client.get("/races/202603220101/odds?bet_type=foobar")
        assert response.status_code == 400
        assert response.json() == {"detail": "unsupported bet_type=foobar"}
    finally:
        app.dependency_overrides.clear()


def test_provider_error_is_returned_as_502():
    app.dependency_overrides[get_service] = lambda: BrokenUpstreamService()
    try:
        client = TestClient(app)
        response = client.get("/meetings/2026-03-22/nakayama")
        assert response.status_code == 502
        assert response.json() == {
            "detail": "failed to fetch https://www.jra.go.jp/JRADB/accessD.html: HTTP 503"
        }
    finally:
        app.dependency_overrides.clear()
