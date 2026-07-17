import asyncio
from datetime import UTC, date, datetime
import json
import sqlite3

from fastapi.testclient import TestClient

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.app import ( 
    app, 
    get_analysis_store, 
    get_nar_netkeiba_service, 
    get_nankankeiba_pattern_service, 
    get_nankan_prediction_service,
    get_nankan_service, 
    get_netkeiba_service,
    get_result_collection_job_registry,
    get_result_storage,
    get_service,
)
from jra_srb.batch import JsonlRaceResultStorage, SQLiteRaceResultStorage
from jra_srb.errors import BadRequestError, ResourceNotFoundError
from jra_srb.jobs import ResultCollectionJobRegistry
from jra_srb.models import (
    MeetingRace,
    MeetingSnapshot,
    NankankeibaPatternBundle,
    NankanLeadingJockeyPage,
    NankanMeetingTrend,
    NankanMeetingTrendContext,
    NankanPredictionBundle,
    NankanPredictionBundleMeta,
    NankanPredictionSummary,
    NankanPredictionSummaryLeadingJockeyItem,
    NankanPredictionSummaryLeadingJockeys,
    NankanPredictionSummaryMeta,
    NankanPredictionSummaryPattern,
    NankanPredictionSummaryRunner,
    NankanPredictionSummaryTrend,
    NankanRaceBestTime,
    NankanRaceClosingSpeed,
    OddsEntry,
    PayoutEntry,
    RaceCard,
    RaceOdds,
    RaceResult,
    RaceSummary,
    ResultEntry,
    Runner,
)
from jra_srb.nankankeiba_pattern_provider import NankankeibaPatternFixtureProvider 
from jra_srb.nankankeiba_pattern_service import NankankeibaPatternService 
from jra_srb.nar_netkeiba_provider import NarNetkeibaFixtureProvider 
from jra_srb.nar_netkeiba_service import NarNetkeibaService
from jra_srb.nankan_provider import NankanFixtureProvider
from jra_srb.nankan_service import NankanService
from jra_srb.netkeiba_provider import NetkeibaFixtureProvider
from jra_srb.netkeiba_service import NetkeibaService
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


def _write_jra_pre_race_api_fixture(store: AnalysisSQLiteStore) -> str:
    race_id = "202607180211"
    store.write_card(
        date(2026, 7, 18),
        "kokura",
        11,
        RaceCard(
            race_id=race_id,
            race_name="Sample Stakes",
            course="kokura",
            distance="1800",
            surface="turf",
            start_time="15:35",
            runners=[Runner(horse_no="1", frame_no="1", horse_name="One")],
            fetched_at=datetime.fromisoformat("2026-07-18T14:55:00+09:00"),
            source="jra",
        ),
    )
    for odds_timing, fetched_at, entries in [
        (
            "t_minus_30m",
            "2026-07-18T15:05:02+09:00",
            [OddsEntry(bet_type="wide", combination=["4", "10"], odds="8.8", popularity="3")],
        ),
        (
            "t_minus_10m",
            "2026-07-18T15:25:02+09:00",
            [OddsEntry(bet_type="wide", combination=["4", "10"], odds="8.5", popularity="3")],
        ),
        (
            "t_minus_2m",
            "2026-07-18T15:33:02+09:00",
            [OddsEntry(bet_type="wide", combination=["2", "9"], odds="7.0")],
        ),
    ]:
        store.write_odds(
            RaceOdds(
                race_id=race_id,
                bet_type="wide",
                entries=entries,
                fetched_at=datetime.fromisoformat(fetched_at),
                source="jra",
            ),
            bet_type="wide",
            odds_timing=odds_timing,
        )
    return race_id


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


def test_get_nankan_leading_jockeys_endpoint():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get(
            "/nankan/leading/jockeys"
            "?course=kawasaki&distance=1400&track_condition=good&period=recent_3months&sort=win_rate"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "nankankeiba"
        assert body["course"] == "kawasaki"
        assert body["distance"] == 1400
        assert body["track_condition"] == "good"
        assert body["period"] == "recent_3months"
        assert body["sort"] == "win_rate"
        assert body["requested_condition_code"] == "211400010004031"
        assert body["effective_condition_code"] == "211400010004031"
        assert body["fallback"] is False
        assert body["items"][0]["jockey_name"] == "野畑凌"
        assert body["items"][0]["win_rate"] == 20.0
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_leading_jockeys_endpoint_accepts_track_condition():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankan_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get(
            "/nankan/leading/jockeys"
            "?course=kawasaki&distance=900&track_condition=good&period=2026&sort=wins"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "nankankeiba"
        assert body["course"] == "kawasaki"
        assert body["distance"] == 900
        assert body["track_condition"] == "good"
        assert body["period"] == "2026"
        assert body["sort"] == "wins"
        assert body["requested_condition_code"] == "210900012026011"
        assert body["effective_condition_code"] == "210900012026011"
        assert body["fallback"] is False
        assert body["items"][0]["jockey_name"] == "川崎900良騎手"
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
        assert body["runners"][0]["horse_weight"] == "470"
        assert body["runners"][0]["horse_weight_diff"] == "+4"
        assert body["runners"][1]["horse_weight"] == "504"
        assert body["runners"][1]["horse_weight_diff"] == "-4"
        assert body["runners"][7]["horse_weight"] == "466"
        assert body["runners"][7]["horse_weight_diff"] == "0"
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


def test_get_netkeiba_race_result_endpoint():
    service = NetkeibaService(provider=NetkeibaFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_netkeiba_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get("/netkeiba/races/202605021211/result")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "202605021211"
        assert body["race_name"] == "日本ダービー"
        assert body["date"] == "2026-05-31"
        assert body["course"] == "東京"
        assert body["results"][0]["horse_name"] == "ロブチェン"
        assert body["results"][0]["win_odds"] == "2.7"
        assert body["results"][0]["popularity"] == "1"
        assert body["results"][0]["horse_weight"] == "522"
        assert body["results"][0]["final_3f"] == "33.2"
        assert any(payout["bet_type"] == "trifecta" for payout in body["payouts"])
    finally:
        app.dependency_overrides.clear()


def test_get_netkeiba_race_odds_endpoint_filters_bet_type_and_combination():
    service = NetkeibaService(provider=NetkeibaFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_netkeiba_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.get("/netkeiba/races/202605021211/odds?bet_type=wide&combination=13,17")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "202605021211"
        assert body["bet_type"] == "wide"
        assert len(body["entries"]) == 1
        assert body["entries"][0]["combination"] == ["13", "17"]
        assert body["entries"][0]["odds_min"] == "5.1"
        assert body["entries"][0]["odds_max"] == "5.6"
        assert body["entries"][0]["popularity"] == "3"
    finally:
        app.dependency_overrides.clear()


def test_get_netkeiba_race_odds_endpoint_matches_unordered_bet_type_combinations_in_reverse_order():
    service = NetkeibaService(provider=NetkeibaFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_netkeiba_service] = lambda: service
    try:
        client = TestClient(app)

        wide_forward = client.get("/netkeiba/races/202605021211/odds?bet_type=wide&combination=13,17")
        wide_reverse = client.get("/netkeiba/races/202605021211/odds?bet_type=wide&combination=17,13")
        quinella_reverse = client.get("/netkeiba/races/202605021211/odds?bet_type=quinella&combination=17,11")
        trio_forward = client.get("/netkeiba/races/202605021211/odds?bet_type=trio&combination=1,11,17")
        trio_reverse = client.get("/netkeiba/races/202605021211/odds?bet_type=trio&combination=17,11,1")

        assert wide_forward.status_code == 200
        assert wide_reverse.status_code == 200
        assert wide_forward.json()["entries"] == wide_reverse.json()["entries"]
        assert wide_reverse.json()["entries"][0]["combination"] == ["13", "17"]
        assert wide_reverse.json()["entries"][0]["odds_min"] == "5.1"
        assert wide_reverse.json()["entries"][0]["odds_max"] == "5.6"

        assert quinella_reverse.status_code == 200
        assert quinella_reverse.json()["entries"][0]["combination"] == ["11", "17"]
        assert quinella_reverse.json()["entries"][0]["odds"] == "7.6"

        assert trio_forward.status_code == 200
        assert trio_reverse.status_code == 200
        assert trio_forward.json()["entries"] == trio_reverse.json()["entries"]
        assert trio_reverse.json()["entries"][0]["combination"] == ["1", "11", "17"]
        assert trio_reverse.json()["entries"][0]["odds"] == "20.7"
    finally:
        app.dependency_overrides.clear()


def test_get_netkeiba_race_odds_endpoint_preserves_ordered_bet_type_combinations():
    service = NetkeibaService(provider=NetkeibaFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_netkeiba_service] = lambda: service
    try:
        client = TestClient(app)

        exacta_forward = client.get("/netkeiba/races/202605021211/odds?bet_type=exacta&combination=17,11")
        exacta_reverse = client.get("/netkeiba/races/202605021211/odds?bet_type=exacta&combination=11,17")
        trifecta_target = client.get("/netkeiba/races/202605021211/odds?bet_type=trifecta&combination=17,13,5")
        trifecta_reordered = client.get("/netkeiba/races/202605021211/odds?bet_type=trifecta&combination=17,5,13")

        assert exacta_forward.status_code == 200
        assert exacta_reverse.status_code == 200
        assert exacta_forward.json()["entries"][0]["combination"] == ["17", "11"]
        assert exacta_forward.json()["entries"][0]["odds"] == "12.0"
        assert exacta_reverse.json()["entries"][0]["combination"] == ["11", "17"]
        assert exacta_reverse.json()["entries"][0]["odds"] == "17.1"

        assert trifecta_target.status_code == 200
        assert trifecta_reordered.status_code == 200
        assert trifecta_target.json()["entries"][0]["combination"] == ["17", "13", "5"]
        assert trifecta_target.json()["entries"][0]["odds"] == "470.5"
        assert trifecta_reordered.json()["entries"][0]["combination"] == ["17", "5", "13"]
        assert trifecta_reordered.json()["entries"][0]["odds"] == "736.9"
    finally:
        app.dependency_overrides.clear()


def test_get_nar_calendar_endpoint_filters_course():
    service = NarNetkeibaService(provider=NarNetkeibaFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nar_netkeiba_service] = lambda: service
    try:
        response = TestClient(app).get("/nar/calendar?year=2026&month=6&course=kawasaki")
        assert response.status_code == 200
        body = response.json()
        assert body["year"] == 2026
        assert body["month"] == 6
        assert len(body["entries"]) == 5
        assert body["entries"][0]["date"] == "2026-06-15"
        assert body["entries"][0]["course_key"] == "kawasaki"
        assert body["entries"][0]["kaisai_id"] == "2026450615"
    finally:
        app.dependency_overrides.clear()


def test_get_nar_meeting_endpoint_returns_races():
    service = NarNetkeibaService(provider=NarNetkeibaFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nar_netkeiba_service] = lambda: service
    try:
        response = TestClient(app).get("/nar/meetings/2026-06-15/kawasaki")
        assert response.status_code == 200
        body = response.json()
        assert body["course"] == "川崎"
        assert len(body["races"]) == 12
        assert body["races"][0]["race_id"] == "202645061501"
        assert body["races"][0]["race_no"] == 1
        assert body["races"][0]["race_name"] == "ラファール賞(3歳)"
        assert body["races"][0]["start_time"] == "15:00"
    finally:
        app.dependency_overrides.clear()


def test_get_nar_race_card_endpoint_returns_weight_and_odds():
    service = NarNetkeibaService(provider=NarNetkeibaFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nar_netkeiba_service] = lambda: service
    try:
        response = TestClient(app).get("/nar/races/202645061501/card")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "202645061501"
        assert body["race_name"] == "ラファール賞(3歳)"
        assert body["surface"] == "ダート"
        assert body["distance"] == "900"
        assert body["start_time"] == "15:00"
        assert body["runners"][0]["horse_name"] == "イアソン"
        assert body["runners"][0]["horse_weight"] == "440"
        assert body["runners"][0]["horse_weight_diff"] == "-7"
        assert body["runners"][0]["odds"] == "129.3"
        assert body["runners"][0]["popularity"] == "8"
    finally:
        app.dependency_overrides.clear()


def test_get_nar_race_result_endpoint_returns_payouts():
    service = NarNetkeibaService(provider=NarNetkeibaFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nar_netkeiba_service] = lambda: service
    try:
        response = TestClient(app).get("/nar/races/202645061501/result")
        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "202645061501"
        assert body["race_name"] == "ラファール賞(3歳)"
        assert body["date"] == "2026-06-15"
        assert body["course"] == "川崎"
        assert body["results"][0]["horse_name"] == "グランドマーメイド"
        assert body["results"][0]["horse_weight"] == "457"
        assert body["results"][0]["horse_weight_diff"] == "-2"
        assert body["results"][0]["win_odds"] == "3.3"
        assert any(payout["bet_type"] == "trifecta" and payout["combination"] == "2-9-4" for payout in body["payouts"])
        assert body["corner_passages"][0].startswith("2")
    finally:
        app.dependency_overrides.clear()


def test_get_nar_race_odds_endpoint_filters_and_normalizes_combination():
    service = NarNetkeibaService(provider=NarNetkeibaFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nar_netkeiba_service] = lambda: service
    try:
        client = TestClient(app)
        wide_reverse = client.get("/nar/races/202645061501/odds?bet_type=wide&combination=4,2")
        exacta_forward = client.get("/nar/races/202645061501/odds?bet_type=exacta&combination=2,4")
        exacta_reverse = client.get("/nar/races/202645061501/odds?bet_type=exacta&combination=4,2")

        assert wide_reverse.status_code == 200
        assert wide_reverse.json()["entries"] == [
            {
                "bet_type": "wide",
                "combination": ["2", "4"],
                "odds": None,
                "odds_min": "1.6",
                "odds_max": "2.0",
                "popularity": None,
            }
        ]

        assert exacta_forward.status_code == 200
        assert exacta_reverse.status_code == 200
        assert exacta_forward.json()["entries"][0]["combination"] == ["2", "4"]
        assert exacta_forward.json()["entries"][0]["odds"] == "7.3"
        assert exacta_reverse.json()["entries"][0]["combination"] == ["4", "2"]
        assert exacta_reverse.json()["entries"][0]["odds"] == "7.8"
    finally:
        app.dependency_overrides.clear()


def test_get_nankankeiba_pattern_endpoint_returns_merged_categories():
    service = NankankeibaPatternService(provider=NankankeibaPatternFixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_nankankeiba_pattern_service] = lambda: service
    try:
        response = TestClient(app).get(
            "/nankankeiba/pattern/meetings/2026-07-06/kawasaki/races/1?meeting_no=4&meeting_day=1"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "202607062104010101"
        assert body["periods"] == ["01"]
        assert body["categories"] == ["pattern_kis", "pattern_uma", "pattern_cho", "pattern_kis_cho"]
        assert len(body["runners"]) == 7
        assert body["runners"][4]["horse_name"] == "ヘヴンリーゴール"
        assert body["runners"][4]["categories"]["pattern_kis"]["rates"]["kawasaki"] == {
            "rate": 14.5,
            "wins": 256,
            "starts": 1770,
        }
        assert body["runners"][4]["categories"]["pattern_uma"]["rates"]["medium"] == {
            "rate": 16.7,
            "wins": 2,
            "starts": 12,
        }
        assert body["runners"][4]["categories"]["pattern_uma"]["rates"]["short"] == {
            "rate": 50.0,
            "wins": 1,
            "starts": 2,
        }
        assert body["runners"][4]["categories"]["pattern_uma"]["track_condition_rates"]["good"] == {
            "rate": 33.3,
            "wins": 2,
            "starts": 6,
        }
    finally:
        app.dependency_overrides.clear()


def test_cli_and_api_return_same_nankankeiba_pattern_json_shape(tmp_path): 
    from jra_srb.cli import build_parser, fetch_nankankeiba_pattern

    service = NankankeibaPatternService(provider=NankankeibaPatternFixtureProvider("tests/fixtures"))
    output = tmp_path / "pattern.json"
    args = build_parser().parse_args(
        [
            "fetch-nankankeiba-pattern",
            "--date",
            "2026-07-06",
            "--course",
            "kawasaki",
            "--meeting",
            "4",
            "--day",
            "1",
            "--race",
            "1",
            "--output",
            str(output),
        ]
    )
    cli_body = json.loads(asyncio.run(fetch_nankankeiba_pattern(args, service=service)))

    app.dependency_overrides[get_nankankeiba_pattern_service] = lambda: service
    try:
        api_body = TestClient(app).get(
            "/nankankeiba/pattern/meetings/2026-07-06/kawasaki/races/1?meeting_no=4&meeting_day=1"
        ).json()
    finally:
        app.dependency_overrides.clear()

    cli_body["cache_hit"] = api_body["cache_hit"] 
    cli_body["meta"] = api_body["meta"] 
    assert cli_body == api_body 


def test_get_nankan_odds_summary_endpoint_returns_default_subset():
    class StubNankanService:
        async def get_race_odds_summary_by_number(self, target_date, course, race_no, bet_types=None, refresh=False):
            assert race_no == 3
            assert bet_types == ["win", "wide", "quinella"]
            return RaceOdds(
                race_id="2026070621040103",
                odds={
                    "win": [OddsEntry(combination=["1"], odds="2.1")],
                    "wide": [OddsEntry(combination=["1", "2"], odds="3.4")],
                    "quinella": [OddsEntry(combination=["1", "2"], odds="5.6")],
                },
                fetched_at=datetime.now(UTC),
                source="stub",
            )

    app.dependency_overrides[get_nankan_service] = lambda: StubNankanService()
    try:
        body = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki/races/3/odds-summary").json()
        assert body["race_id"] == "2026070621040103"
        assert set(body["odds"].keys()) == {"win", "wide", "quinella"}
        assert "trifecta" not in body["odds"]
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_odds_summary_endpoint_rejects_unsupported_summary_bet_type():
    response = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki/races/1/odds-summary?bet_types=trifecta")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


def test_get_nankan_prediction_bundle_endpoint_returns_materials():
    class StubPredictionService:
        async def get_prediction_bundle(
            self,
            target_date: date,
            course: str,
            race_no: int,
            meeting_no: int,
            meeting_day: int,
            bet_types: list[str] | None = None,
            refresh: bool = False,
        ) -> NankanPredictionBundle:
            trend = NankanMeetingTrend(
                date=target_date,
                course=course,
                meeting_id="2026210401",
                open_date="20260706",
                fetched_at=datetime.now(UTC),
                source="fixture:trend",
            )
            return NankanPredictionBundle(
                race_id="2026070621040101",
                date=target_date,
                course=course,
                race_no=race_no,
                meeting_no=meeting_no,
                meeting_day=meeting_day,
                odds_bet_types=bet_types or ["win", "wide", "quinella"],
                card=RaceCard(race_id="2026070621040101", fetched_at=datetime.now(UTC), source="fixture:card"),
                odds_summary=RaceOdds(
                    race_id="2026070621040101",
                    odds={"win": [], "wide": [], "quinella": []},
                    fetched_at=datetime.now(UTC),
                    source="fixture:odds",
                ),
                trend_context=NankanMeetingTrendContext(
                    date=target_date,
                    course=course,
                    race_no=race_no,
                    race_count_completed=0,
                    required_max_completed=0,
                    usable=True,
                    fetched_at=datetime.now(UTC),
                    source="fixture:trend",
                    trend=trend,
                ),
                best_time=NankanRaceBestTime(
                    race_id="2026070621040101",
                    fetched_at=datetime.now(UTC),
                    source="fixture:best-time",
                ),
                closing_speed=NankanRaceClosingSpeed(
                    race_id="2026070621040101",
                    fetched_at=datetime.now(UTC),
                    source="fixture:closing-speed",
                ),
                pattern=NankankeibaPatternBundle(
                    race_id="202607062104010101",
                    date=target_date,
                    course=course,
                    meeting_no=meeting_no,
                    meeting_day=meeting_day,
                    race_no=race_no,
                    fetched_at=datetime.now(UTC),
                    source="fixture:pattern",
                ),
                leading_jockeys=NankanLeadingJockeyPage(
                    course=course,
                    period="recent_3months",
                    sort="win_rate",
                    generated_at=datetime.now(UTC),
                ),
                fetched_at=datetime.now(UTC),
                meta=NankanPredictionBundleMeta(parallelized=True, used_existing_services=True),
            )

    app.dependency_overrides[get_nankan_prediction_service] = lambda: StubPredictionService()
    try:
        body = TestClient(app).get(
            "/nankan/meetings/2026-07-06/kawasaki/races/1/prediction-bundle?meeting_no=4&meeting_day=1"
        ).json()
        assert body["race_id"] == "2026070621040101"
        assert body["odds_bet_types"] == ["win", "wide", "quinella"]
        assert body["card"]["race_id"] == "2026070621040101"
        assert body["odds_summary"]["race_id"] == "2026070621040101"
        assert body["trend_context"]["race_no"] == 1
        assert body["best_time"]["race_id"] == "2026070621040101"
        assert body["closing_speed"]["race_id"] == "2026070621040101"
        assert body["pattern"]["meeting_no"] == 4
        assert body["leading_jockeys"]["course"] == "kawasaki"
        assert body["meta"]["parallelized"] is True
        assert body["meta"]["used_existing_services"] is True
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_prediction_bundle_endpoint_requires_meeting_parameters():
    response = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki/races/1/prediction-bundle")
    assert response.status_code == 422


def test_get_nankan_prediction_summary_endpoint_returns_compact_materials():
    class StubPredictionService:
        async def get_prediction_summary(
            self,
            target_date: date,
            course: str,
            race_no: int,
            meeting_no: int,
            meeting_day: int,
            bet_types: list[str] | None = None,
            refresh: bool = False,
        ) -> NankanPredictionSummary:
            return NankanPredictionSummary(
                race_id="2026070621040101",
                date=target_date,
                course=course,
                race_no=race_no,
                meeting_no=meeting_no,
                meeting_day=meeting_day,
                distance="900",
                track_condition="good",
                trend=NankanPredictionSummaryTrend(
                    race_count_completed=0,
                    required_max_completed=0,
                    usable=True,
                ),
                leading_jockeys=NankanPredictionSummaryLeadingJockeys(
                    course=course,
                    distance=900,
                    track_condition="good",
                    period="recent_3months",
                    sort="win_rate",
                    items=[
                        NankanPredictionSummaryLeadingJockeyItem(
                            rank=1,
                            jockey_name="笹川翼",
                            win_rate=21.5,
                        )
                    ],
                ),
                runners=[
                    NankanPredictionSummaryRunner(
                        frame_no="1",
                        horse_no="1",
                        horse_name="テストホース",
                        win_odds="2.4",
                        popularity="1",
                        pattern=NankanPredictionSummaryPattern(),
                    )
                ],
                meta=NankanPredictionSummaryMeta(
                    odds_bet_types=bet_types or ["win", "wide", "quinella"],
                    cache_hit=False,
                ),
            )

    app.dependency_overrides[get_nankan_prediction_service] = lambda: StubPredictionService()
    try:
        body = TestClient(app).get(
            "/nankan/meetings/2026-07-06/kawasaki/races/1/prediction-summary?meeting_no=4&meeting_day=1"
        ).json()
        assert body["race_id"] == "2026070621040101"
        assert body["distance"] == "900"
        assert body["trend"]["usable"] is True
        assert body["leading_jockeys"]["items"][0]["jockey_name"] == "笹川翼"
        assert body["runners"][0]["horse_name"] == "テストホース"
        assert body["meta"]["odds_bet_types"] == ["win", "wide", "quinella"]
    finally:
        app.dependency_overrides.clear()


def test_get_nankan_prediction_summary_endpoint_requires_meeting_parameters():
    response = TestClient(app).get("/nankan/meetings/2026-07-06/kawasaki/races/1/prediction-summary")
    assert response.status_code == 422


def test_mcp_exposes_only_documented_read_only_tools():
    expected_tools = [
        "normalize_race_input",
        "search_jra_races",
        "get_jra_meeting",
        "get_jra_race_card",
        "get_jra_race_odds",
        "get_jra_race_result",
        "get_jra_prediction_bundle",
        "get_jra_odds_summary",
        "compare_jra_prediction_models",
        "get_jra_betting_decision",
    ]
    headers = {"accept": "application/json, text/event-stream"}

    with TestClient(app) as client:
        initialize_response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            },
        )
        assert initialize_response.status_code == 200
        assert initialize_response.json()["result"]["serverInfo"]["name"] == "JRA Race MCP"

        headers["mcp-session-id"] = initialize_response.headers["mcp-session-id"]
        initialized_response = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert initialized_response.status_code == 202

        tools_response = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert tools_response.status_code == 200
        tools = tools_response.json()["result"]["tools"]
        assert [tool["name"] for tool in tools] == expected_tools

        normalize_tool = tools[0]
        assert "日本語や自然な表記" in normalize_tool["description"]
        assert normalize_tool["inputSchema"]["properties"]["course"]["description"] == (
            "開催場名またはコード。例: 中山, nakayama"
        )

        call_response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "normalize_race_input",
                    "arguments": {
                        "course": "中山",
                        "race": "11R",
                        "bet_type": "3連単",
                        "combination": "1,2,3",
                    },
                },
            },
        )
        assert call_response.status_code == 200
        result = call_response.json()["result"]
        assert result["isError"] is False
        assert json.loads(result["content"][0]["text"]) == {
            "course": "nakayama",
            "race_no": 11,
            "bet_type": "trifecta",
            "combination": ["1", "2", "3"],
        }


def test_normalize_endpoint_returns_canonical_values():
    client = TestClient(app)
    response = client.get("/normalize?course=中山&race=11R&bet_type=3連単&combination=1,2,3")

    assert response.status_code == 200
    assert response.json() == {
        "course": "nakayama",
        "race_no": 11,
        "bet_type": "trifecta",
        "combination": ["1", "2", "3"],
    }


def test_invalid_race_no_is_rejected_by_path_validation():
    client = TestClient(app)
    response = client.get("/meetings/2026-03-22/nakayama/races/13/card", headers={"x-request-id": "req-validation"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["request_id"] == "req-validation"


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
    snapshot_get = body["paths"]["/jra/races/{race_id}/pre-race-snapshot"]["get"]
    timeline_get = body["paths"]["/jra/races/{race_id}/odds-timeline"]["get"]
    assert snapshot_get["summary"] == "保存済みJRA発走前snapshotを取得"
    assert timeline_get["summary"] == "保存済みJRAオッズ時系列を取得"
    snapshot_parameters = {item["name"]: item for item in snapshot_get["parameters"]}
    timeline_parameters = {item["name"]: item for item in timeline_get["parameters"]}
    assert "読み込みません" in snapshot_parameters["include_odds"]["description"]
    assert "カンマ区切り" in timeline_parameters["combination"]["description"]
    assert snapshot_get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/StoredPreRaceSnapshot"
    )
    assert timeline_get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/StoredOddsTimeline"
    )
    assert "ApiErrorResponse" in body["components"]["schemas"]


def test_post_bet_records_endpoint_expands_wide_box(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    app.dependency_overrides[get_analysis_store] = lambda: store
    try:
        client = TestClient(app)
        response = client.post(
            "/bet-records",
            json={
                "race_id": "202607051011",
                "decision_source": "manual",
                "total_amount": 400,
                "tickets": [
                    {
                        "bet_type": "wide",
                        "mode": "box",
                        "selection": ["2", "4", "10"],
                        "amount_per_ticket": 100,
                    },
                    {
                        "bet_type": "trio",
                        "selection": ["2", "4", "10"],
                        "amount": 100,
                    },
                ],
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["race_id"] == "202607051011"
        assert body["total_amount"] == 400
        assert [ticket["selection"] for ticket in body["tickets"]] == ["2-4", "2-10", "4-10", "2-4-10"]
        assert [ticket["is_box_expanded"] for ticket in body["tickets"]] == [True, True, True, False]
    finally:
        app.dependency_overrides.clear()


def test_bet_records_endpoints_accept_16_digit_nankan_race_id(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    app.dependency_overrides[get_analysis_store] = lambda: store
    try:
        client = TestClient(app)
        created = client.post(
            "/bet-records",
            json={
                "race_id": "2026070419040501",
                "decision_source": "manual",
                "total_amount": 100,
                "tickets": [{"bet_type": "win", "selection": ["1"], "amount": 100}],
            },
        )

        assert created.status_code == 201
        created_body = created.json()
        assert created_body["race_id"] == "2026070419040501"
        assert created_body["tickets"][0]["race_id"] == "2026070419040501"

        by_id = client.get(f"/bet-records/{created_body['bet_record_id']}")
        listed = client.get("/bet-records?race_id=2026070419040501")

        assert by_id.status_code == 200
        assert by_id.json()["race_id"] == "2026070419040501"
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["bet_record_id"] == created_body["bet_record_id"]
    finally:
        app.dependency_overrides.clear()


def test_bet_record_endpoint_rejects_invalid_race_id_lengths(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    app.dependency_overrides[get_analysis_store] = lambda: store
    try:
        client = TestClient(app)
        for race_id in ("20260705101", "202607041904050"):
            response = client.post(
                "/bet-records",
                json={
                    "race_id": race_id,
                    "decision_source": "manual",
                    "total_amount": 100,
                    "tickets": [{"bet_type": "win", "selection": ["1"], "amount": 100}],
                },
            )
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "validation_error"

            listed = client.get(f"/bet-records?race_id={race_id}")
            assert listed.status_code == 422
            assert listed.json()["error"]["code"] == "validation_error"
    finally:
        app.dependency_overrides.clear()


def test_get_bet_record_endpoint_returns_prediction_link(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    record = store.create_bet_record(
        {
            "race_id": "202607051011",
            "prediction_id": "pred-1",
            "theory_version": "v1",
            "decision_source": "agent",
            "total_amount": 100,
            "tickets": [
                {
                    "prediction_ticket_id": "pt-1",
                    "bucket": "core",
                    "bet_type": "wide",
                    "selection": ["2", "10"],
                    "amount": 100,
                }
            ],
        }
    )
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            """
            insert into predictions
            (prediction_id, race_id, theory_version, mode, budget, pre_race_snapshot_json, prediction_json, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("pred-1", "202607051011", "v1", "auto", 1000, "{}", "{\"score\": 0.8}", datetime.now(UTC).isoformat()),
        )
        conn.execute(
            """
            insert into prediction_tickets
            (ticket_id, prediction_id, race_id, bucket, bet_type, selection, selection_json, amount, reason)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("pt-1", "pred-1", "202607051011", "core", "wide", "2-10", "[\"2\", \"10\"]", 100, "seed"),
        )

    app.dependency_overrides[get_analysis_store] = lambda: store
    try:
        response = TestClient(app).get(f"/bet-records/{record.bet_record_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["prediction"]["prediction_id"] == "pred-1"
        assert body["prediction_tickets"][0]["ticket_id"] == "pt-1"
        assert body["tickets"][0]["prediction_ticket_id"] == "pt-1"
    finally:
        app.dependency_overrides.clear()


def test_settle_bet_record_endpoint_returns_zero_for_all_miss(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    store.write_result(
        RaceResult(
            race_id="202607051011",
            race_name="Kitakyushu Kinen",
            results=[],
            payouts=[PayoutEntry(bet_type="wide", combination="1-3", payout="800")],
            fetched_at=datetime.now(UTC),
            source="result",
        )
    )
    record = store.create_bet_record(
        {
            "race_id": "202607051011",
            "decision_source": "manual",
            "total_amount": 400,
            "tickets": [
                {"bet_type": "wide", "mode": "box", "selection": ["2", "4", "10"], "amount_per_ticket": 100},
                {"bet_type": "trio", "selection": ["2", "4", "10"], "amount": 100},
            ],
        }
    )

    app.dependency_overrides[get_analysis_store] = lambda: store
    try:
        response = TestClient(app).post(f"/bet-records/{record.bet_record_id}/settle")

        assert response.status_code == 200
        body = response.json()
        assert body["total_bet"] == 400
        assert body["total_payout"] == 0
        assert body["hit"] is False
    finally:
        app.dependency_overrides.clear()


def test_settle_bet_record_endpoint_supports_16_digit_nankan_race_id(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    store.write_result(
        RaceResult(
            race_id="2026070419040501",
            race_name="Nankan Sample",
            results=[],
            payouts=[PayoutEntry(bet_type="単勝", combination="1", payout="1,830")],
            fetched_at=datetime.now(UTC),
            source="nankan-result",
        )
    )
    record = store.create_bet_record(
        {
            "race_id": "2026070419040501",
            "decision_source": "manual",
            "total_amount": 100,
            "tickets": [{"bet_type": "win", "selection": ["1"], "amount": 100}],
        }
    )
    app.dependency_overrides[get_analysis_store] = lambda: store
    try:
        response = TestClient(app).post(f"/bet-records/{record.bet_record_id}/settle")

        assert response.status_code == 200
        body = response.json()
        assert body["race_id"] == "2026070419040501"
        assert body["total_payout"] == 1830
        assert body["hit"] is True
    finally:
        app.dependency_overrides.clear()


class MissingRaceService:
    async def get_race_card(self, race_id: str):
        raise ResourceNotFoundError(f"race not found for race_id={race_id}")


class UnsupportedBetTypeService:
    async def get_race_odds(self, race_id: str, **kwargs):
        raise BadRequestError("unsupported bet_type=foobar")


class BrokenUpstreamService:
    async def get_meeting(self, target_date, course: str):
        raise ProviderError("failed to fetch https://www.jra.go.jp/JRADB/accessD.html: HTTP 503")


class HealthyUpstreamService:
    async def check_upstream(self):
        return {"status": "ok", "source": "fixture"}


class FakeResultCollectionService:
    def __init__(self, fail_result: bool = False) -> None:
        self.fail_result = fail_result

    async def get_meeting(self, target_date: date, course: str) -> MeetingSnapshot:
        return MeetingSnapshot(
            date=target_date,
            course=course,
            races=[
                MeetingRace(race_no=1, race_id=f"{target_date:%Y%m%d}0601", race_name="1R"),
                MeetingRace(race_no=2, race_id=f"{target_date:%Y%m%d}0602", race_name="2R"),
            ],
            fetched_at=datetime.now(UTC),
            source="fake",
        )

    async def get_race_result_by_number(self, target_date: date, course: str, race_no: int) -> RaceResult:
        if self.fail_result:
            raise RuntimeError("fake result failure")
        return RaceResult(
            race_id=f"{target_date:%Y%m%d}06{race_no:02d}",
            race_name=f"{race_no}R",
            results=[
                ResultEntry(
                    rank="1",
                    horse_no=str(race_no),
                    horse_name=f"Horse {race_no}",
                    jockey="Jockey",
                    time="1:10.0",
                )
            ],
            payouts=[PayoutEntry(bet_type="win", combination=str(race_no), payout="100", popularity="1")],
            fetched_at=datetime.now(UTC),
            source="fake",
        )


class FakeRaceSearchService:
    async def get_races(self, target_date: date, course: str | None = None) -> list[RaceSummary]:
        return [
            RaceSummary(
                race_id="202603220601",
                race_number="1R",
                name="Morning Sprint",
                course="nakayama",
                start_time="10:00",
            ),
            RaceSummary(
                race_id="202603220611",
                race_number="11R",
                name="Chiba Stakes",
                course="nakayama",
                start_time="15:45",
            ),
        ]


def test_not_found_error_is_returned_as_404():
    app.dependency_overrides[get_service] = lambda: MissingRaceService()
    try:
        client = TestClient(app)
        response = client.get("/races/202603220101/card", headers={"x-request-id": "req-404"})
        assert response.status_code == 404
        assert response.json() == {
            "error": {
                "code": "not_found",
                "message": "race not found for race_id=202603220101",
                "request_id": "req-404",
            }
        }
    finally:
        app.dependency_overrides.clear()


def test_bad_request_error_is_returned_as_400():
    client = TestClient(app)
    response = client.get("/races/202603220101/odds?bet_types=foobar", headers={"x-request-id": "req-400"})

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "bad_request",
            "message": "unsupported bet_type=foobar",
            "request_id": "req-400",
        }
    }


def test_provider_error_is_returned_as_502():
    app.dependency_overrides[get_service] = lambda: BrokenUpstreamService()
    try:
        client = TestClient(app)
        response = client.get("/meetings/2026-03-22/nakayama", headers={"x-request-id": "req-502"})
        assert response.status_code == 502
        assert response.json() == {
            "error": {
                "code": "upstream_error",
                "message": "failed to fetch https://www.jra.go.jp/JRADB/accessD.html: HTTP 503",
                "request_id": "req-502",
            }
        }
    finally:
        app.dependency_overrides.clear()


def test_health_upstream_endpoint():
    app.dependency_overrides[get_service] = lambda: HealthyUpstreamService()
    try:
        client = TestClient(app)
        response = client.get("/health/upstream")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "source": "fixture"}
    finally:
        app.dependency_overrides.clear()


def test_result_collection_job_api_collects_results(tmp_path):
    registry = ResultCollectionJobRegistry()
    output = tmp_path / "job-results.jsonl"
    app.dependency_overrides[get_service] = lambda: FakeResultCollectionService()
    app.dependency_overrides[get_result_collection_job_registry] = lambda: registry
    try:
        client = TestClient(app)
        created = client.post(
            "/jobs/result-collections",
            json={
                "from_date": "2026-03-22",
                "to_date": "2026-03-22",
                "courses": ["nakayama"],
                "storage": "jsonl",
                "output": str(output),
                "retries": 0,
            },
        )

        assert created.status_code == 202
        assert created.json()["status"] == "queued"
        job_id = created.json()["job_id"]

        detail = client.get(f"/jobs/result-collections/{job_id}")
        listed = client.get("/jobs/result-collections")

        assert detail.status_code == 200
        assert detail.json()["status"] == "succeeded"
        assert detail.json()["error"] is None
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert len(output.read_text(encoding="utf-8").splitlines()) == 2
    finally:
        app.dependency_overrides.clear()


def test_result_collection_job_api_records_failure(tmp_path):
    registry = ResultCollectionJobRegistry()
    output = tmp_path / "job-results.jsonl"
    app.dependency_overrides[get_service] = lambda: FakeResultCollectionService(fail_result=True)
    app.dependency_overrides[get_result_collection_job_registry] = lambda: registry
    try:
        client = TestClient(app)
        created = client.post(
            "/jobs/result-collections",
            json={
                "from_date": "2026-03-22",
                "to_date": "2026-03-22",
                "courses": ["nakayama"],
                "storage": "jsonl",
                "output": str(output),
            },
        )
        job_id = created.json()["job_id"]

        detail = client.get(f"/jobs/result-collections/{job_id}")

        assert detail.status_code == 200
        assert detail.json()["status"] == "failed"
        assert detail.json()["error"] == "fake result failure"
    finally:
        app.dependency_overrides.clear()


def test_result_collection_job_not_found_returns_404():
    registry = ResultCollectionJobRegistry()
    app.dependency_overrides[get_result_collection_job_registry] = lambda: registry
    try:
        response = TestClient(app).get("/jobs/result-collections/missing", headers={"x-request-id": "req-job-404"})

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert response.json()["error"]["request_id"] == "req-job-404"
    finally:
        app.dependency_overrides.clear()


def test_search_races_filters_keyword_and_pages_results():
    app.dependency_overrides[get_service] = lambda: FakeRaceSearchService()
    try:
        response = TestClient(app).get("/search/races?date=2026-03-22&course=nakayama&keyword=11R&limit=1&offset=0")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["limit"] == 1
        assert body["offset"] == 0
        assert body["items"][0]["race_id"] == "202603220611"
        assert body["items"][0]["race_no"] == 11
        assert body["items"][0]["race_name"] == "Chiba Stakes"
    finally:
        app.dependency_overrides.clear()


def test_stored_result_endpoints(tmp_path):
    storage = JsonlRaceResultStorage(tmp_path / "results.jsonl")
    service = JraService(provider=FixtureProvider("tests/fixtures"))
    app.dependency_overrides[get_result_storage] = lambda: storage
    app.dependency_overrides[get_service] = lambda: service
    try:
        result = TestClient(app).get("/meetings/2026-03-22/nakayama/races/11/result").json()
        storage.write_result(
            date(2026, 3, 22),
            "nakayama",
            11,
            RaceResult.model_validate(result),
        )

        client = TestClient(app)
        by_id = client.get("/stored/results/202603220611")
        listed = client.get("/stored/results?from_date=2026-03-22&to_date=2026-03-22&course=nakayama&limit=1&offset=0")

        assert by_id.status_code == 200
        assert by_id.json()["race_id"] == "202603220611"
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["limit"] == 1
        assert listed.json()["offset"] == 0
        assert len(listed.json()["items"]) == 1
    finally:
        app.dependency_overrides.clear()


def test_stored_result_endpoint_reads_sqlite_storage_from_env(tmp_path, monkeypatch):
    path = tmp_path / "results.sqlite"
    storage = SQLiteRaceResultStorage(path)
    service = JraService(provider=FixtureProvider("tests/fixtures"))
    monkeypatch.setenv("JRA_SRB_RESULTS_STORAGE", "sqlite")
    monkeypatch.setenv("JRA_SRB_RESULTS_PATH", str(path))
    app.dependency_overrides[get_service] = lambda: service
    try:
        result = TestClient(app).get("/meetings/2026-03-22/nakayama/races/11/result").json()
        storage.write_result(date(2026, 3, 22), "nakayama", 11, RaceResult.model_validate(result))
        response = TestClient(app).get("/stored/results/202603220611")

        assert response.status_code == 200
        assert response.json()["race_id"] == "202603220611"
    finally:
        app.dependency_overrides.clear()


def test_invalid_result_storage_env_returns_standard_error(monkeypatch):
    monkeypatch.setenv("JRA_SRB_RESULTS_STORAGE", "bad")

    response = TestClient(app).get("/stored/results")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"
    assert response.json()["error"]["message"] == "unsupported results storage=bad"


def test_jra_prediction_and_evaluation_read_endpoints(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    store.upsert_prediction_record(
        {
            "prediction_id": "pred-api-read-1",
            "race_id": "202607051011",
            "theory_version": "v-api-read",
            "mode": "integrated",
            "budget": 1000,
            "pre_race_snapshot": {"date": "2026-07-05", "course": "kokura", "race_no": 11},
            "prediction_json": {"axis": "2"},
            "prediction_tickets": [
                {
                    "ticket_id": "pt-api-read-1",
                    "bucket": "core",
                    "bet_type": "wide",
                    "selection": ["2", "10"],
                    "amount": 1000,
                }
            ],
        }
    )
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            """
            insert into evaluations
            (evaluation_id, prediction_id, race_id, theory_version, total_bet, total_payout,
             return_rate, hit, gami, axis_in_top3, middle_hole_in_top3, firework_hit,
             max_odds_selected, evaluation_json, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "eval-api-read-1", "pred-api-read-1", "202607051011", "v-api-read",
                1000, 1800, 1.8, 1, 0, 1, None, 0, 18.0, '{"status":"reviewed"}',
                "2026-07-05T16:00:00+00:00",
            ),
        )
        conn.execute(
            """
            insert into evaluation_ticket_results
            (ticket_result_id, evaluation_id, ticket_id, bucket, bet_type, selection, amount, hit, payout)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("etr-api-read-1", "eval-api-read-1", "pt-api-read-1", "core", "wide", "2-10", 1000, 1, 1800),
        )

    app.dependency_overrides[get_analysis_store] = lambda: store
    try:
        client = TestClient(app)

        prediction_detail = client.get("/jra/predictions/pred-api-read-1")
        prediction_list = client.get(
            "/jra/predictions?from_date=2026-07-05&to_date=2026-07-05&theory_version=v-api-read"
        )
        evaluation_detail = client.get("/jra/evaluations/eval-api-read-1")
        evaluation_list = client.get("/jra/evaluations?prediction_id=pred-api-read-1")
        evaluation_summary = client.get("/jra/evaluations/summary?theory_version=v-api-read")

        assert prediction_detail.status_code == 200
        assert prediction_detail.json()["prediction"] == {"axis": "2"}
        assert prediction_detail.json()["prediction_tickets"][0]["selection_json"] == ["2", "10"]
        assert prediction_list.status_code == 200
        assert prediction_list.json()["total"] == 1
        assert evaluation_detail.status_code == 200
        assert evaluation_detail.json()["hit"] is True
        assert evaluation_detail.json()["middle_hole_in_top3"] is None
        assert evaluation_list.status_code == 200
        assert evaluation_list.json()["items"][0]["evaluation_id"] == "eval-api-read-1"
        assert evaluation_summary.status_code == 200
        assert evaluation_summary.json()["return_rate"] == 1.8
        assert evaluation_summary.json()["max_single_payout"] == 1800
    finally:
        app.dependency_overrides.clear()


def test_jra_prediction_and_evaluation_read_endpoints_validate_queries_and_not_found(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    app.dependency_overrides[get_analysis_store] = lambda: store
    try:
        client = TestClient(app)

        assert client.get("/jra/predictions/missing").status_code == 404
        assert client.get("/jra/evaluations/missing").status_code == 404
        reversed_range = client.get("/jra/evaluations?from_date=2026-07-06&to_date=2026-07-05")
        invalid_race_id = client.get("/jra/predictions?race_id=invalid")
        invalid_limit = client.get("/jra/evaluations?limit=501")

        assert reversed_range.status_code == 400
        assert reversed_range.json()["error"]["code"] == "bad_request"
        assert invalid_race_id.status_code == 422
        assert invalid_limit.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_jra_pre_race_snapshot_and_odds_timeline_read_analysis_db_from_env(tmp_path, monkeypatch):
    path = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(path)
    race_id = _write_jra_pre_race_api_fixture(store)
    monkeypatch.setenv("JRA_SRB_ANALYSIS_DB_PATH", str(path))

    client = TestClient(app)
    snapshot_response = client.get(f"/jra/races/{race_id}/pre-race-snapshot")
    no_odds_response = client.get(
        f"/jra/races/{race_id}/pre-race-snapshot?include_odds=false"
    )
    timeline_response = client.get(
        f"/jra/races/{race_id}/odds-timeline?bet_type=wide&combination=10,4"
    )

    assert snapshot_response.status_code == 200
    snapshot = snapshot_response.json()
    assert snapshot["race"]["race_date"] == "2026-07-18"
    assert snapshot["runners"][0]["card_odds"] is None
    assert snapshot["odds"][0]["odds_timing"] == "t_minus_2m"
    assert snapshot["meta"]["available_odds_timings"] == [
        "t_minus_30m",
        "t_minus_10m",
        "t_minus_2m",
    ]
    assert "results" not in snapshot
    assert "payouts" not in snapshot
    assert "evaluations" not in snapshot

    assert no_odds_response.status_code == 200
    no_odds = no_odds_response.json()
    assert no_odds["odds"] == []
    assert no_odds["meta"]["available_odds_timings"] == []
    assert no_odds["meta"]["missing_components"] == []

    assert timeline_response.status_code == 200
    timeline = timeline_response.json()
    assert timeline["combination"] == ["4", "10"]
    assert timeline["total"] == 3
    assert [item["odds_timing"] for item in timeline["snapshots"]] == [
        "t_minus_30m",
        "t_minus_10m",
        "t_minus_2m",
    ]
    assert timeline["snapshots"][2]["entries"] == []
    assert "combination_json" not in timeline_response.text


def test_jra_pre_race_snapshot_and_odds_timeline_validate_requests(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    race_id = _write_jra_pre_race_api_fixture(store)
    app.dependency_overrides[get_analysis_store] = lambda: store
    try:
        client = TestClient(app)

        missing_race = client.get("/jra/races/202607180212/pre-race-snapshot")
        missing_timeline_race = client.get(
            "/jra/races/202607180212/odds-timeline?bet_type=wide"
        )
        invalid_race_id = client.get("/jra/races/invalid/pre-race-snapshot")
        invalid_bool = client.get(
            f"/jra/races/{race_id}/pre-race-snapshot?include_odds=invalid"
        )
        missing_bet_type = client.get(f"/jra/races/{race_id}/odds-timeline")
        invalid_bet_type = client.get(
            f"/jra/races/{race_id}/odds-timeline?bet_type=foobar"
        )
        invalid_combination = client.get(
            f"/jra/races/{race_id}/odds-timeline?bet_type=wide&combination=4"
        )
        no_saved_odds = client.get(
            f"/jra/races/{race_id}/odds-timeline?bet_type=trifecta"
        )

        assert missing_race.status_code == 404
        assert missing_race.json()["error"]["code"] == "not_found"
        assert missing_timeline_race.status_code == 404
        assert missing_timeline_race.json()["error"]["code"] == "not_found"
        assert invalid_race_id.status_code == 422
        assert invalid_bool.status_code == 422
        assert missing_bet_type.status_code == 422
        assert invalid_bet_type.status_code == 422
        assert invalid_combination.status_code == 400
        assert invalid_combination.json()["error"]["code"] == "bad_request"
        assert no_saved_odds.status_code == 200
        assert no_saved_odds.json()["snapshots"] == []
        assert no_saved_odds.json()["total"] == 0
    finally:
        app.dependency_overrides.clear()
