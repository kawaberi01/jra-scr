from fastapi.testclient import TestClient

from jra_srb.app import app, get_nankan_service
from jra_srb.errors import ResourceNotFoundError
from jra_srb.nankan_provider import NankanFixtureProvider, NankanPageContent
from jra_srb.nankan_service import NankanService


def test_get_nankan_meeting_endpoint():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/meetings/2026-07-04/funabashi")
        assert response.status_code == 200
        body = response.json()
        assert body["course"] == "funabashi"
        assert body["races"][0]["race_id"] == "2026070419040501"
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_kawasaki_meeting_endpoint_includes_conditions():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki")
        assert response.status_code == 200
        body = response.json()
        race = next(item for item in body["races"] if item["race_no"] == 11)
        assert body["weather"] == "rainy"
        assert body["track_condition"] == "heavy"
        assert body["surface"] == "dirt"
        assert race["race_id"] == "2026070621040111"
        assert race["surface"] == "dirt"
        assert race["distance"] == "2000"
        assert race["start_time"] == "20:15"
        assert race["weather"] == "rainy"
        assert race["track_condition"] == "heavy"
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_card_endpoint_returns_horse_weight_data_status():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/races/2026070419040501/card")
        assert response.status_code == 200
        body = response.json()
        assert body["data_status"]["horse_weight"] == "available"
        assert body["data_status"]["horse_weight_reason"] == "at least one runner has horse_weight or horse_weight_diff"
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_card_endpoint_returns_unpublished_horse_weight_status():
    service = NankanService(provider=UnpublishedWeightCardProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/races/2026070721040201/card")
        assert response.status_code == 200
        body = response.json()
        assert body["data_status"]["horse_weight"] == "unpublished"
        assert body["data_status"]["horse_weight_reason"] == "all runners have null horse_weight before official publication"
        assert all(runner["horse_weight"] is None for runner in body["runners"])
        assert all(runner["horse_weight_diff"] is None for runner in body["runners"])
    finally:
        app.dependency_overrides.clear()


def test_nankan_card_openapi_schema_includes_data_status():
    body = TestClient(app).get("/openapi.json").json()

    race_card_schema = body["components"]["schemas"]["RaceCard"]
    data_status_ref = race_card_schema["properties"]["data_status"]["anyOf"][0]["$ref"]
    data_status_schema_name = data_status_ref.rsplit("/", 1)[-1]
    data_status_schema = body["components"]["schemas"][data_status_schema_name]

    assert "data_status" in race_card_schema["properties"]
    assert "horse_weight" in data_status_schema["properties"]
    assert "horse_weight_reason" in data_status_schema["properties"]


def test_get_nankan_odds_endpoint_filters_bet_type_and_combination():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/races/2026070419040501/odds?bet_type=wide&combination=2,1")
        assert response.status_code == 200
        body = response.json()
        assert body["bet_type"] == "wide"
        assert body["entries"][0]["combination"] == ["1", "2"]
        assert body["entries"][0]["odds_min"] == "33.3"
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_win_odds_endpoint_returns_card_runner_count_by_race_id():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/races/2026070621040103/odds?bet_type=win")
        assert response.status_code == 200
        body = response.json()
        assert body["bet_type"] == "win"
        assert len(body["entries"]) == 12
        assert [entry["combination"][0] for entry in body["entries"]] == [str(number) for number in range(1, 13)]
        assert body["entries"][11]["odds"] is None
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_win_odds_endpoint_returns_card_runner_count_by_number():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki/races/3/odds?bet_type=win")
        assert response.status_code == 200
        body = response.json()
        assert len(body["entries"]) == 12
        assert [entry["combination"][0] for entry in body["entries"]] == [str(number) for number in range(1, 13)]
        assert body["entries"][5]["odds"] == "6.6"
        assert body["entries"][7]["odds"] == "8.8"
        assert body["entries"][9]["odds"] == "10.1"
        assert body["entries"][11]["odds"] is None
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_result_endpoint():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/races/2026070419040501/result")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "2026070419040501"
        assert body["results"][0]["horse_name"] == "イデスホープ"
        assert body["payouts"][0]["bet_type"] == "win"
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_kawasaki_result_endpoint():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/races/2026070621040101/result")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "2026070621040101"
        assert body["results"][0]["horse_no"] == "5"
        assert body["payouts"][3]["combination"] == "3-5"
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_result_endpoint_by_number():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/meetings/2026-07-04/funabashi/races/1/result")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "2026070419040501"
        assert body["results"][0]["rank"] == "1"
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_kawasaki_result_endpoint_by_number():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki/races/1/result")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "2026070621040101"
        assert body["results"][0]["horse_name"] == "ヘヴンリーゴール"
        assert body["payouts"][-1]["bet_type"] == "trifecta"
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_kawasaki_11r_card_endpoint_keeps_horse_no_9():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki/races/11/card")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "2026070621040111"
        assert body["race_name"] == "アクルックス賞"
        assert body["surface"] == "dirt"
        assert body["surface_label"] == "ダ"
        assert body["distance"] == "2000"
        assert body["start_time"] == "20:15"
        assert body["weather"] == "rainy"
        assert body["weather_label"] == "雨"
        assert body["track_condition"] == "heavy"
        assert body["track_condition_label"] == "重"
        assert [runner["horse_no"] for runner in body["runners"]] == [str(number) for number in range(1, 10)]
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_kawasaki_11r_card_endpoint_by_race_id_has_conditions():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/races/2026070621040111/card")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "2026070621040111"
        assert body["surface"] == "dirt"
        assert body["distance"] == "2000"
        assert body["start_time"] == "20:15"
        assert body["weather"] == "rainy"
        assert body["track_condition"] == "heavy"
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_meeting_trend_endpoint():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki/trend")
        assert response.status_code == 200
        body = response.json()
        assert body["date"] == "2026-07-06"
        assert body["course"] == "kawasaki"
        assert body["meeting_id"] == "2026210401"
        assert body["open_date"] == "20260706"
        assert body["updated_at"] == "2026-07-06T21:24:00+09:00"
        assert body["race_count_completed"] == 12
        assert body["summary"]["frame"][0] == {"frame_no": "6", "top3_count": 8}
        assert body["summary"]["running_style"]["front_group_top3_count"] == 27
        assert body["summary"]["running_style"]["back_group_top3_count"] == 9
        assert body["summary"]["jockey"][0] == {"name": "笹川翼", "affiliation": "大井", "top3_count": 5}
        assert body["summary"]["trainer"][0] == {"name": "高月賢一", "affiliation": "川崎", "top3_count": 5}
        assert body["summary"]["payout"]["trifecta_max_payout"] == 109080
        assert "nankan_trend_2026210401_20260706.html" in body["source"]
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_meeting_trend_context_endpoint_rejects_post_race_snapshot():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki/races/6/trend-context")
        assert response.status_code == 200
        body = response.json()
        assert body["race_no"] == 6
        assert body["race_count_completed"] == 12
        assert body["required_max_completed"] == 5
        assert body["usable"] is False
        assert body["reason"] == "latest trend is post-race snapshot"
        assert body["summary"]["frame"] == []
        assert body["trend"]["summary"]["frame"][0]["frame_no"] == "6"
    finally:
        app.dependency_overrides.clear()


def test_nankan_trend_context_openapi_schema_is_registered():
    body = TestClient(app).get("/openapi.json").json()

    assert "/nankan/meetings/{date_}/{course}/races/{race_no}/trend-context" in body["paths"]
    assert "NankanMeetingTrendContext" in body["components"]["schemas"]


def test_get_nankan_best_time_endpoint_by_number():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki/races/1/best-time")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "2026070621040101"
        assert body["course"] == "kawasaki"
        assert body["distance"] == 1400
        assert body["runners"][0]["horse_no"] == "5"
        assert body["runners"][0]["best_time"] == "1:31.8"
        assert body["runners"][0]["same_course_flag"] is True
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_closing_speed_endpoint_by_number():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki/races/1/closing-speed")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "2026070621040101"
        assert body["runners"][0]["horse_no"] == "5"
        assert body["runners"][0]["best_closing_time"] == "39.5"
        assert body["runners"][0]["closing_section_distance"] == 600
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_style_profile_endpoint_by_number():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki/races/1/style-profile")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "2026070621040101"
        assert body["runners"][0]["horse_no"] == "5"
        assert body["runners"][0]["sample_size"] == 2
        assert body["runners"][0]["expected_style"] == "front"
        assert body["runners"][0]["recent_races"][0]["corner_positions"] == [7, 7, 4]
    finally:
        app.dependency_overrides.clear()


def test_nankan_16_digit_race_id_is_validated_independently():
    response = TestClient(app).get("/nankan/races/202607041904/odds")

    assert response.status_code == 422


def test_nankan_result_16_digit_race_id_validation():
    response = TestClient(app).get("/nankan/races/202607041904/result")

    assert response.status_code == 422


class MissingResultProvider(NankanFixtureProvider):
    async def fetch_result(self, race_id: str) -> NankanPageContent:
        raise ResourceNotFoundError(f"nankan result not available yet: race_id={race_id}")


class UnpublishedWeightCardProvider(NankanFixtureProvider):
    async def fetch_race_card(self, race_id: str) -> NankanPageContent:
        return NankanPageContent(source=f"fixture:{race_id}", content=_unpublished_weight_card_html())


def _unpublished_weight_card_html() -> str:
    return """
    <html><body>
      <h1>1R 川崎 ダ1400m 発走時刻 15:00 天候:晴 馬場:ダ良</h1>
      <p>Ｃ３(一)(二)</p>
      <table>
        <tr><th>枠</th><th>馬</th><th>馬名</th><th>性齢</th><th>単勝</th><th>馬体重</th><th>斤量</th><th>騎手</th><th></th><th>調教師</th><th></th></tr>
        <tr><td>1</td><td>1</td><td>テストホースA</td><td>牡4</td><td>2.1</td><td></td><td>56.0</td><td>町田直希</td><td></td><td>テスト厩舎</td><td></td></tr>
        <tr><td>2</td><td>2</td><td>テストホースB</td><td>牝5</td><td>4.8</td><td></td><td>54.0</td><td>野畑凌</td><td></td><td>テスト厩舎</td><td></td></tr>
      </table>
    </body></html>
    """


def test_nankan_result_not_available_returns_404():
    service = NankanService(provider=MissingResultProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        response = TestClient(app).get("/nankan/races/2026070419040501/result")
        assert response.status_code == 404
        assert "result not available yet" in response.json()["error"]["message"]
    finally:
        app.dependency_overrides.clear()
