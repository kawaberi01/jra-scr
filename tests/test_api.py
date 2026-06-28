from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from jra_srb.app import app, get_result_collection_job_registry, get_result_storage, get_service
from jra_srb.batch import JsonlRaceResultStorage, SQLiteRaceResultStorage
from jra_srb.errors import BadRequestError, ResourceNotFoundError
from jra_srb.jobs import ResultCollectionJobRegistry
from jra_srb.models import MeetingRace, MeetingSnapshot, PayoutEntry, RaceResult, RaceSummary, ResultEntry
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
    assert "ApiErrorResponse" in body["components"]["schemas"]


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
