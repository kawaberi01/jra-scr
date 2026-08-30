from datetime import UTC, date, datetime
import json

import httpx
import pytest

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.cli import ( 
    build_parser, 
    call_local_api, 
    collect_analysis, 
    collect_netkeiba_results, 
    collect_results, 
    fetch_nankan_prediction_bundle,
    fetch_nankankeiba_pattern, 
    generate_netkeiba_mapping, 
    parse_jra_bet_type_offsets,
) 
from jra_srb.daily_prediction_log_importer import import_daily_prediction_log, parse_daily_prediction_log
from jra_srb.models import MeetingRace, MeetingSnapshot, NetkeibaRaceResult, RaceResult
from jra_srb.models import NetkeibaResultEntry, PayoutEntry
from jra_srb.nankankeiba_pattern_provider import NankankeibaPatternFixtureProvider
from jra_srb.nankankeiba_pattern_service import NankankeibaPatternService


class FakeCliService:
    async def get_meeting(self, target_date: date, course: str) -> MeetingSnapshot:
        return MeetingSnapshot(
            date=target_date,
            course=course,
            races=[MeetingRace(race_no=1, race_id=f"{target_date:%Y%m%d}0601")],
            fetched_at=datetime.now(UTC),
            source="fake",
        )

    async def get_meetings_for_date(self, target_date: date) -> list[MeetingSnapshot]:
        return [await self.get_meeting(target_date, "nakayama")]

    async def get_race_result_by_number(self, target_date: date, course: str, race_no: int) -> RaceResult:
        return RaceResult(
            race_id=f"{target_date:%Y%m%d}06{race_no:02d}",
            fetched_at=datetime.now(UTC),
            source="fake",
        )

    async def get_race_card_by_number(self, target_date: date, course: str, race_no: int):
        from jra_srb.models import RaceCard, Runner

        return RaceCard(
            race_id=f"{target_date:%Y%m%d}06{race_no:02d}",
            race_name="Fake Race",
            course=course,
            runners=[Runner(horse_no="1", horse_name="Fake Horse")],
            fetched_at=datetime.now(UTC),
            source="fake",
        )


class FakeNetkeibaCliService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_race_result(self, race_id: str) -> NetkeibaRaceResult:
        self.calls.append(race_id)
        return NetkeibaRaceResult(
            race_id=race_id,
            race_name="Netkeiba Sample",
            date="2026-05-02",
            course="Tokyo",
            race_no="11",
            results=[
                NetkeibaResultEntry(
                    rank="1",
                    horse_no="1",
                    horse_name="Sample Horse",
                    win_odds="5.0",
                )
            ],
            payouts=[PayoutEntry(bet_type="wide", combination="1-2", payout="1,000", popularity="1")],
            fetched_at=datetime.now(UTC),
            source="fake-netkeiba",
        )


class FakeNarCliService:
    async def get_meeting(self, target_date: date, course: str) -> MeetingSnapshot:
        return MeetingSnapshot(
            date=target_date,
            course=course,
            races=[MeetingRace(race_no=1, race_id="202645061501", race_name="Nar Sample")],
            fetched_at=datetime.now(UTC),
            source="nar-meeting",
        )

    async def get_race_card(self, race_id: str):
        from jra_srb.models import RaceCard, Runner

        return RaceCard(
            race_id=race_id,
            race_name="Nar Sample",
            course="kawasaki",
            runners=[Runner(horse_no="1", horse_name="Nar Horse")],
            fetched_at=datetime.now(UTC),
            source="nar-card",
        )

    async def get_race_result(self, race_id: str) -> NetkeibaRaceResult:
        return NetkeibaRaceResult(
            race_id=race_id,
            race_name="Nar Sample",
            race_no="1",
            results=[NetkeibaResultEntry(rank="1", horse_no="1", horse_name="Nar Horse")],
            payouts=[PayoutEntry(bet_type="wide", combination="1-2", payout="860", popularity="3")],
            fetched_at=datetime.now(UTC),
            source="nar-result",
        )


@pytest.mark.asyncio
async def test_collect_results_cli_uses_normalized_course_and_writes_jsonl(tmp_path):
    args = type(
        "Args",
        (),
        {
            "storage": "jsonl",
            "output": tmp_path / "results.jsonl",
            "courses": "中山",
            "from_date": date(2026, 3, 22),
            "to_date": date(2026, 3, 22),
            "retries": 0,
        },
    )()

    await collect_results(args, service=FakeCliService())  # type: ignore[arg-type]

    assert (tmp_path / "results.jsonl").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_collect_results_cli_accepts_all_for_auto_discovery(tmp_path):
    args = type(
        "Args",
        (),
        {
            "storage": "jsonl",
            "output": tmp_path / "results.jsonl",
            "courses": "all",
            "from_date": date(2026, 3, 22),
            "to_date": date(2026, 3, 22),
            "retries": 0,
        },
    )()

    await collect_results(args, service=FakeCliService())  # type: ignore[arg-type]

    assert (tmp_path / "results.jsonl").read_text(encoding="utf-8")


def test_cli_parser_accepts_analysis_maintenance_commands(tmp_path):
    parser = build_parser()

    backfill = parser.parse_args(
        [
            "backfill-analysis-runners",
            "--db",
            str(tmp_path / "analysis.sqlite"),
            "--from-date",
            "2026-03-22",
            "--to-date",
            "2026-03-22",
            "--courses",
            "all",
            "--only-missing",
            "--retries",
            "1",
            "--min-interval-seconds",
            "0.1",
            "--limit",
            "5",
            "--dry-run",
        ]
    )
    verify = parser.parse_args(
        [
            "verify-analysis-joins",
            "--db",
            str(tmp_path / "analysis.sqlite"),
            "--from-date",
            "2026-03-22",
            "--to-date",
            "2026-03-22",
            "--sample-size",
            "3",
        ]
    )

    assert backfill.command == "backfill-analysis-runners"
    assert backfill.only_missing is True
    assert verify.command == "verify-analysis-joins"
    assert verify.sample_size == 3


def test_cli_parser_accepts_refresh_existing_for_jra_odds_timeline(tmp_path):
    parser = build_parser()

    args = parser.parse_args(
        [
            "collect-jra-odds-timeline",
            "--date",
            "2026-07-18",
            "--db",
            str(tmp_path / "analysis.sqlite"),
            "--refresh-existing",
        ]
    )

    assert args.command == "collect-jra-odds-timeline"
    assert args.refresh_existing is True


def test_parse_jra_bet_type_offsets_accepts_per_bet_type_offsets() -> None:
    parsed = parse_jra_bet_type_offsets(
        "win=30,10,2;quinella=30,10,2;wide=30,10,2;trio=10,2"
    )

    assert parsed == {
        "win": [30, 10, 2],
        "quinella": [30, 10, 2],
        "wide": [30, 10, 2],
        "trio": [10, 2],
    }


@pytest.mark.parametrize("value", ["", "win=", "win=-2", "unknown=10", "win=10;win=2"])
def test_parse_jra_bet_type_offsets_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_jra_bet_type_offsets(value)


def test_cli_parser_accepts_fetch_nankankeiba_pattern(tmp_path):
    parser = build_parser()

    args = parser.parse_args(
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
            "--periods",
            "lifetime",
            "--output",
            str(tmp_path / "pattern.json"),
        ]
    )

    assert args.command == "fetch-nankankeiba-pattern"
    assert args.target_date == date(2026, 7, 6)
    assert args.meeting_no == 4
    assert args.meeting_day == 1
    assert args.race_no == 1


def test_cli_parser_accepts_call_local_api(tmp_path): 
    parser = build_parser()

    args = parser.parse_args(
        [
            "call-local-api",
            "/nankan/meetings/2026-07-08/kawasaki/races/8/odds",
            "--query",
            "bet_type=wide",
            "--output",
            str(tmp_path / "api.json"),
        ]
    )

    assert args.command == "call-local-api" 
    assert args.path == "/nankan/meetings/2026-07-08/kawasaki/races/8/odds" 
    assert args.query == ["bet_type=wide"] 


def test_cli_parser_accepts_fetch_nankan_prediction_bundle(tmp_path):
    parser = build_parser()

    args = parser.parse_args(
        [
            "fetch-nankan-prediction-bundle",
            "--date",
            "2026-07-08",
            "--course",
            "kawasaki",
            "--race",
            "11",
            "--meeting",
            "4",
            "--day",
            "2",
            "--output",
            str(tmp_path / "bundle.json"),
        ]
    )

    assert args.command == "fetch-nankan-prediction-bundle"
    assert args.target_date == date(2026, 7, 8)
    assert args.race_no == 11
    assert args.meeting_no == 4
    assert args.meeting_day == 2


def test_cli_parser_accepts_import_daily_prediction_log(tmp_path): 
    parser = build_parser()

    args = parser.parse_args(
        [
            "import-daily-prediction-log",
            str(tmp_path / "daily.md"),
            "--db",
            str(tmp_path / "analysis.sqlite"),
        ]
    )

    assert args.command == "import-daily-prediction-log"
    assert args.path == tmp_path / "daily.md"


def test_parse_and_import_daily_prediction_log(tmp_path):
    markdown = """# 2026-07-08 川崎競馬 予想ログ

## ログ

### 2026-07-08 19:55:30
- 種別: 事前予想
- 対象: 川崎 11R サンプル
- 予想モード: 総合買い目型
- 使用データ:
  - オッズ: yes
"""
    source = tmp_path / "daily.md"
    source.write_text(markdown, encoding="utf-8")

    parsed = parse_daily_prediction_log(markdown)

    assert parsed.log_date == "2026-07-08"
    assert parsed.venue == "川崎競馬"
    assert parsed.entries[0].course == "kawasaki"
    assert parsed.entries[0].race_no == 11

    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    store.write_race(
        date(2026, 7, 8),
        "kawasaki",
        MeetingRace(race_no=11, race_id="2026070821040311", race_name="Sample"),
        source="meeting",
        fetched_at=datetime.now(UTC),
    )

    summary = import_daily_prediction_log(store, source)

    assert summary.imported_entries == 1
    assert summary.resolved_race_ids == 1


@pytest.mark.asyncio
async def test_call_local_api_writes_pretty_json(tmp_path): 
    output = tmp_path / "api.json"
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"race": "8R", "odds": [1, 2, 3]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        args = type(
            "Args",
            (),
            {
                "base_url": "http://127.0.0.1:8000",
                "path": "/nankan/meetings/2026-07-08/kawasaki/races/8/odds",
                "query": ["bet_type=wide"],
                "output": output,
            },
        )()
        text = await call_local_api(args, client=client)  # type: ignore[arg-type]

    assert captured["url"] == "http://127.0.0.1:8000/nankan/meetings/2026-07-08/kawasaki/races/8/odds?bet_type=wide"
    assert output.read_text(encoding="utf-8") == text + "\n" 
    assert json.loads(text) == {"race": "8R", "odds": [1, 2, 3]} 


@pytest.mark.asyncio
async def test_fetch_nankan_prediction_bundle_calls_local_api_once(tmp_path):
    output = tmp_path / "bundle.json"
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"race_id": "2026070821040211", "status": "ok"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        args = type(
            "Args",
            (),
            {
                "target_date": date(2026, 7, 8),
                "course": "kawasaki",
                "race_no": 11,
                "meeting_no": 4,
                "meeting_day": 2,
                "bet_types": "win,wide,quinella",
                "base_url": "http://127.0.0.1:8000",
                "refresh": True,
                "output": output,
            },
        )()
        text = await fetch_nankan_prediction_bundle(args, client=client)  # type: ignore[arg-type]

    assert (
        captured["url"]
        == "http://127.0.0.1:8000/nankan/meetings/2026-07-08/kawasaki/races/11/prediction-bundle"
        "?meeting_no=4&meeting_day=2&bet_types=win%2Cwide%2Cquinella&refresh=true"
    )
    assert output.read_text(encoding="utf-8") == text + "\n"
    assert json.loads(text) == {"race_id": "2026070821040211", "status": "ok"}


@pytest.mark.asyncio 
async def test_fetch_nankankeiba_pattern_writes_json(tmp_path): 
    parser = build_parser()
    output = tmp_path / "pattern.json"
    args = parser.parse_args(
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
    service = NankankeibaPatternService(provider=NankankeibaPatternFixtureProvider("tests/fixtures"))

    text = await fetch_nankankeiba_pattern(args, service=service)

    assert output.read_text(encoding="utf-8") == text + "\n"
    assert '"race_id": "202607062104010101"' in text
    assert '"horse_name": "ヘヴンリーゴール"' in text
    body = json.loads(text)
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


def test_cli_parser_accepts_collect_analysis_min_interval(tmp_path):
    parser = build_parser()

    args = parser.parse_args(
        [
            "collect-analysis",
            "--db",
            str(tmp_path / "analysis.sqlite"),
            "--from-date",
            "2026-03-22",
            "--to-date",
            "2026-03-22",
            "--courses",
            "nakayama",
            "--include-card",
            "--include-results",
            "--min-interval-seconds",
            "1.5",
            "--max-live-requests",
            "10",
            "--skip-existing",
        ]
    )

    assert args.command == "collect-analysis"
    assert args.min_interval_seconds == 1.5
    assert args.max_live_requests == 10
    assert args.skip_existing is True


@pytest.mark.asyncio
async def test_collect_analysis_passes_min_interval_option(tmp_path):
    args = type(
        "Args",
        (),
        {
            "db": tmp_path / "analysis.sqlite",
            "courses": "nakayama",
            "from_date": date(2026, 3, 22),
            "to_date": date(2026, 3, 22),
            "include_card": True,
            "include_odds": False,
            "include_results": True,
            "bet_types": "wide",
            "odds_timing": "final_or_near_final",
            "retries": 0,
            "min_interval_seconds": 0.0,
        },
    )()

    run_id = await collect_analysis(args, service=FakeCliService())  # type: ignore[arg-type]

    assert run_id


@pytest.mark.asyncio
async def test_collect_analysis_accepts_kawasaki_and_writes_sqlite(tmp_path):
    args = type(
        "Args",
        (),
        {
            "db": tmp_path / "analysis.sqlite",
            "courses": "kawasaki",
            "from_date": date(2026, 6, 15),
            "to_date": date(2026, 6, 15),
            "include_card": True,
            "include_odds": False,
            "include_results": True,
            "bet_types": "wide",
            "odds_timing": "final_or_near_final",
            "retries": 0,
            "min_interval_seconds": 0.0,
            "max_live_requests": 10,
            "skip_existing": True,
        },
    )()

    run_id = await collect_analysis(
        args,
        service=FakeCliService(),  # type: ignore[arg-type]
        nar_service=FakeNarCliService(),  # type: ignore[arg-type]
    )
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")

    assert run_id
    assert store.count_rows("races") == 1
    assert store.count_rows("runners") == 1
    assert store.count_rows("result_entries") == 1
    assert store.count_rows("payouts") == 1


def test_cli_parser_accepts_collect_netkeiba_results(tmp_path):
    parser = build_parser()

    args = parser.parse_args(
        [
            "collect-netkeiba-results",
            "--db",
            str(tmp_path / "analysis.sqlite"),
            "--mapping-csv",
            str(tmp_path / "mapping.csv"),
            "--from-date",
            "2026-05-01",
            "--to-date",
            "2026-05-31",
            "--max-live-requests",
            "3",
            "--min-interval-seconds",
            "0",
            "--refresh",
            "--dry-run",
            "--limit",
            "2",
        ]
    )

    assert args.command == "collect-netkeiba-results"
    assert args.max_live_requests == 3
    assert args.refresh is True
    assert args.dry_run is True
    assert args.limit == 2

    db_args = parser.parse_args(
        [
            "collect-netkeiba-results",
            "--db",
            str(tmp_path / "analysis.sqlite"),
            "--use-db-mapping",
            "--from-date",
            "2026-05-01",
            "--to-date",
            "2026-05-31",
            "--dry-run",
        ]
    )

    assert db_args.command == "collect-netkeiba-results"
    assert db_args.mapping_csv is None
    assert db_args.use_db_mapping is True


@pytest.mark.asyncio
async def test_collect_netkeiba_results_writes_and_skips_saved_results(tmp_path):
    mapping = tmp_path / "mapping.csv"
    mapping.write_text(
        "\n".join(
            [
                "jra_race_id,netkeiba_race_id,race_date,course,race_no",
                "202606280301,202605021211,2026-05-02,tokyo,11",
            ]
        ),
        encoding="utf-8",
    )
    args = type(
        "Args",
        (),
        {
            "db": tmp_path / "analysis.sqlite",
            "mapping_csv": mapping,
            "use_db_mapping": False,
            "from_date": date(2026, 5, 1),
            "to_date": date(2026, 5, 31),
            "max_live_requests": 30,
            "min_interval_seconds": 0.0,
            "refresh": False,
            "retries": 0,
            "dry_run": False,
            "limit": None,
        },
    )()
    service = FakeNetkeibaCliService()

    first = await collect_netkeiba_results(args, service=service)  # type: ignore[arg-type]
    second = await collect_netkeiba_results(args, service=service)  # type: ignore[arg-type]

    assert first.collected_count == 1
    assert first.skipped_count == 0
    assert second.collected_count == 0
    assert second.skipped_count == 1
    assert service.calls == ["202605021211"]


@pytest.mark.asyncio
async def test_collect_netkeiba_results_stops_at_live_request_limit(tmp_path):
    mapping = tmp_path / "mapping.csv"
    mapping.write_text(
        "\n".join(
            [
                "jra_race_id,netkeiba_race_id,race_date,course,race_no",
                "202606280301,202605021211,2026-05-02,tokyo,11",
                "202606280302,202605021212,2026-05-02,tokyo,12",
            ]
        ),
        encoding="utf-8",
    )
    args = type(
        "Args",
        (),
        {
            "db": tmp_path / "analysis.sqlite",
            "mapping_csv": mapping,
            "use_db_mapping": False,
            "from_date": date(2026, 5, 1),
            "to_date": date(2026, 5, 31),
            "max_live_requests": 1,
            "min_interval_seconds": 0.0,
            "refresh": False,
            "retries": 0,
            "dry_run": False,
            "limit": None,
        },
    )()
    service = FakeNetkeibaCliService()

    summary = await collect_netkeiba_results(args, service=service)  # type: ignore[arg-type]

    assert summary.collected_count == 1
    assert summary.live_request_limit_reached is True
    assert service.calls == ["202605021211"]


@pytest.mark.asyncio
async def test_collect_netkeiba_results_dry_run_does_not_call_live_service_and_reports_counts(tmp_path):
    mapping = tmp_path / "mapping.csv"
    mapping.write_text(
        "\n".join(
            [
                "jra_race_id,netkeiba_race_id,race_date,course,race_no,mapping_status,mapping_note",
                "202606280301,202605021211,2026-05-02,tokyo,11,mapped,ok",
                "202606280302,,2026-05-02,tokyo,12,unmapped,no calendar",
            ]
        ),
        encoding="utf-8",
    )
    args = type(
        "Args",
        (),
        {
            "db": tmp_path / "analysis.sqlite",
            "mapping_csv": mapping,
            "use_db_mapping": False,
            "from_date": date(2026, 5, 1),
            "to_date": date(2026, 5, 31),
            "max_live_requests": 30,
            "min_interval_seconds": 0.0,
            "refresh": False,
            "retries": 0,
            "dry_run": True,
            "limit": None,
        },
    )()
    service = FakeNetkeibaCliService()

    summary = await collect_netkeiba_results(args, service=service)  # type: ignore[arg-type]

    assert summary.dry_run is True
    assert summary.target_count == 2
    assert summary.saved_count == 0
    assert summary.unsaved_count == 1
    assert summary.planned_request_count == 1
    assert summary.unmappable_count == 1
    assert service.calls == []


@pytest.mark.asyncio
async def test_collect_netkeiba_results_limit_restricts_targets_before_collection(tmp_path):
    mapping = tmp_path / "mapping.csv"
    mapping.write_text(
        "\n".join(
            [
                "jra_race_id,netkeiba_race_id,race_date,course,race_no",
                "202606280301,202605021211,2026-05-02,tokyo,11",
                "202606280302,202605021212,2026-05-02,tokyo,12",
            ]
        ),
        encoding="utf-8",
    )
    args = type(
        "Args",
        (),
        {
            "db": tmp_path / "analysis.sqlite",
            "mapping_csv": mapping,
            "use_db_mapping": False,
            "from_date": date(2026, 5, 1),
            "to_date": date(2026, 5, 31),
            "max_live_requests": 30,
            "min_interval_seconds": 0.0,
            "refresh": False,
            "retries": 0,
            "dry_run": False,
            "limit": 1,
        },
    )()
    service = FakeNetkeibaCliService()

    summary = await collect_netkeiba_results(args, service=service)  # type: ignore[arg-type]

    assert summary.target_count == 1
    assert summary.collected_count == 1
    assert service.calls == ["202605021211"]


def test_generate_netkeiba_mapping_restores_course_from_jra_race_id_and_writes_unmapped_rows(tmp_path):
    db = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(db)
    store.write_race(
        date(2026, 5, 2),
        "course: 1,600m dirt left",
        MeetingRace(race_no=11, race_id="202605020511", race_name="Mapped"),
    )
    with store._connect() as conn:
        conn.execute(
            """
            insert into races (race_id, race_date, course, race_no, race_name)
            values (?, ?, ?, ?, ?)
            """,
            ("bad-race-id", "2026-05-02", "tokyo", 12, "Unmapped"),
        )
    output = tmp_path / "mapping.csv"
    args = type(
        "Args",
        (),
        {
            "db": db,
            "from_date": date(2026, 5, 1),
            "to_date": date(2026, 5, 31),
            "output": output,
            "meeting_calendar_csv": None,
            "save_to_db": False,
            "limit": None,
        },
    )()

    summary = generate_netkeiba_mapping(args)
    lines = output.read_text(encoding="utf-8").splitlines()

    assert summary.total_count == 2
    assert summary.mapped_count == 1
    assert summary.unmapped_count == 1
    assert lines[0] == "jra_race_id,netkeiba_race_id,race_date,course,race_no,mapping_status,mapping_note"
    assert "mapped_estimated" in lines[1]
    assert ",tokyo," in lines[1]
    assert "unmapped" in lines[2]
    assert "invalid jra_race_id=bad-race-id" in lines[2]


@pytest.mark.asyncio
async def test_generate_netkeiba_mapping_saves_to_db_and_collect_dry_run_uses_db_mapping(tmp_path):
    db = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(db)
    store.write_race(
        date(2026, 5, 2),
        "course: 1,600m dirt left",
        MeetingRace(race_no=11, race_id="202605020511", race_name="Mapped"),
    )
    with store._connect() as conn:
        conn.execute(
            """
            insert into races (race_id, race_date, course, race_no, race_name)
            values (?, ?, ?, ?, ?)
            """,
            ("bad-race-id", "2026-05-02", "tokyo", 12, "Unmapped"),
        )
    generate_args = type(
        "Args",
        (),
        {
            "db": db,
            "from_date": date(2026, 5, 1),
            "to_date": date(2026, 5, 31),
            "output": None,
            "meeting_calendar_csv": None,
            "save_to_db": True,
            "limit": None,
        },
    )()

    summary = generate_netkeiba_mapping(generate_args)

    assert summary.output is None
    assert summary.saved_to_db is True
    assert summary.mapped_count == 1
    assert summary.unmapped_count == 1

    collect_args = type(
        "Args",
        (),
        {
            "db": db,
            "mapping_csv": None,
            "use_db_mapping": True,
            "from_date": date(2026, 5, 1),
            "to_date": date(2026, 5, 31),
            "max_live_requests": 30,
            "min_interval_seconds": 0.0,
            "refresh": False,
            "retries": 0,
            "dry_run": True,
            "limit": None,
        },
    )()
    service = FakeNetkeibaCliService()

    collect_summary = await collect_netkeiba_results(collect_args, service=service)  # type: ignore[arg-type]

    assert collect_summary.dry_run is True
    assert collect_summary.target_count == 2
    assert collect_summary.unsaved_count == 1
    assert collect_summary.unmappable_count == 1
    assert collect_summary.planned_request_count == 1
    assert service.calls == []


def test_generate_netkeiba_mapping_uses_calendar_context_before_from_date(tmp_path):
    db = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(db)
    store.write_race(
        date(2025, 10, 4),
        "tokyo",
        MeetingRace(race_no=1, race_id="202510040501", race_name="Context"),
    )
    store.write_race(
        date(2025, 10, 5),
        "tokyo",
        MeetingRace(race_no=11, race_id="202510050511", race_name="Target"),
    )
    calendar = tmp_path / "calendar.csv"
    calendar.write_text(
        "\n".join(
            [
                "course,meeting_no,start_date,start_day_no",
                "tokyo,4,2025-10-04,1",
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "mapping.csv"
    args = type(
        "Args",
        (),
        {
            "db": db,
            "from_date": date(2025, 10, 5),
            "to_date": date(2025, 10, 5),
            "output": output,
            "meeting_calendar_csv": calendar,
            "save_to_db": False,
            "limit": None,
        },
    )()

    summary = generate_netkeiba_mapping(args)
    lines = output.read_text(encoding="utf-8").splitlines()

    assert summary.total_count == 1
    assert "202505040211" in lines[1]
    assert "mapping_status,mapping_note" in lines[0]


class FakePredictionNankanService:
    async def _race_id_by_number(self, target_date: date, course: str, race_no: int, refresh: bool):
        return "2026070921040401"

    async def get_race_card(self, race_id: str, refresh: bool = False):
        from jra_srb.models import CachePolicyMeta, RaceCard, Runner

        return RaceCard(
            race_id=race_id,
            race_name="Trace Race",
            course="kawasaki",
            distance="1400",
            track_condition="good",
            runners=[Runner(horse_no="1", horse_name="Trace Horse")],
            fetched_at=datetime.now(UTC),
            source="fake",
            cache_hit=True,
            meta=CachePolicyMeta(data_source="db", db_hit=True, ttl_expired=False, saved=False, stale=False),
        )

    async def get_meeting_trend_context(self, target_date: date, course: str, race_no: int, refresh: bool = False):
        from jra_srb.models import NankanMeetingTrendContext

        return NankanMeetingTrendContext(
            date=target_date,
            course=course,
            race_no=race_no,
            race_count_completed=0,
            required_max_completed=0,
            usable=True,
            fetched_at=datetime.now(UTC),
            source="fake",
        )

    async def get_race_odds(self, race_id: str, bet_types=None, refresh: bool = False, card=None):
        from jra_srb.models import CachePolicyMeta, OddsEntry, RaceOdds

        return RaceOdds(
            race_id=race_id,
            odds={"win": [OddsEntry(bet_type="win", combination=["1"], odds="2.1")]},
            fetched_at=datetime.now(UTC),
            source="fake",
            cache_hit=False,
            meta=CachePolicyMeta(data_source="external", db_hit=False, ttl_expired=False, saved=True, stale=False),
        )

    async def get_race_best_time(self, race_id: str, refresh: bool = False, card=None):
        from jra_srb.models import NankanBestTimeRunner, NankanRaceBestTime

        return NankanRaceBestTime(
            race_id=race_id,
            runners=[NankanBestTimeRunner(horse_no="1", horse_name="Trace Horse")],
            fetched_at=datetime.now(UTC),
            source="fake",
        )

    async def get_race_closing_speed(self, race_id: str, refresh: bool = False, card=None):
        from jra_srb.models import NankanClosingSpeedRunner, NankanRaceClosingSpeed

        return NankanRaceClosingSpeed(
            race_id=race_id,
            runners=[NankanClosingSpeedRunner(horse_no="1", horse_name="Trace Horse")],
            fetched_at=datetime.now(UTC),
            source="fake",
        )

    async def get_leading_jockeys(self, **kwargs):
        from jra_srb.models import NankanLeadingJockeyPage

        return NankanLeadingJockeyPage(
            period="recent_3months",
            sort="win_rate",
            generated_at=datetime.now(UTC),
            items=[],
        )

    @staticmethod
    def _distance_int(value: str | None) -> int | None:
        return int(value) if value else None

    @staticmethod
    def _normalize_leading_distance(value: int | None) -> int | None:
        return value

    @staticmethod
    def _normalize_leading_track_condition(value: str | None) -> str | None:
        return value


class FakePredictionPatternService:
    async def get_pattern_bundle(
        self,
        target_date: date,
        course: str,
        meeting_no: int,
        meeting_day: int,
        race_no: int,
        refresh: bool = False,
    ):
        from jra_srb.models import NankankeibaPatternBundle

        return NankankeibaPatternBundle(
            race_id="2026070921040401",
            date=target_date,
            course=course,
            meeting_no=meeting_no,
            meeting_day=meeting_day,
            race_no=race_no,
            categories=["pattern_kis"],
            fetched_at=datetime.now(UTC),
            source="fake",
        )


@pytest.mark.asyncio
async def test_nankan_prediction_bundle_trace_writes_utf8_jsonl(tmp_path):
    from jra_srb.nankan_prediction_service import NankanPredictionService
    from jra_srb.prediction_trace import PredictionTraceLogger

    trace_path = tmp_path / "prediction-trace.jsonl"
    service = NankanPredictionService(
        nankan_service=FakePredictionNankanService(),  # type: ignore[arg-type]
        pattern_service=FakePredictionPatternService(),  # type: ignore[arg-type]
        trace_logger=PredictionTraceLogger(trace_path),
    )

    await service.get_prediction_bundle(
        date(2026, 7, 9),
        "kawasaki",
        1,
        4,
        4,
        bet_types=["win", "wide"],
        refresh=True,
    )

    lines = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert any(line["event_type"] == "prediction_bundle" and line["phase"] == "start" for line in lines)
    assert any(line["event_type"] == "prediction_bundle" and line["phase"] == "done" for line in lines)
    assert any(line["event_type"] == "card" and line["phase"] == "done" for line in lines)
    odds_done = next(line for line in lines if line["event_type"] == "odds_summary" and line["phase"] == "done")
    assert odds_done["summary"]["meta"]["data_source"] == "external"
    assert odds_done["summary"]["odds_counts"]["win"] == 1


def test_prediction_trace_logger_appends_to_base_file_even_with_request_trace_id(tmp_path):
    from jra_srb.prediction_trace import PredictionTraceLogger

    base_path = tmp_path / "prediction-trace.jsonl"
    logger = PredictionTraceLogger(base_path)

    logger.write("http_request", request_trace_id="req-a", phase="start")
    logger.write("http_request", request_trace_id="req-b", phase="start")

    assert base_path.exists()
    lines = [json.loads(line) for line in base_path.read_text(encoding="utf-8").splitlines()]
    assert [line["request_trace_id"] for line in lines] == ["req-a", "req-b"]
