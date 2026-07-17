from datetime import UTC, date, datetime
import sqlite3

import pytest

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.errors import BadRequestError
from jra_srb.models import (
    BetRecordCreateRequest,
    JraDayRaceScoutEntry,
    JraDayRaceScoutResult,
    JraLiveShadowObservation,
    MeetingRace,
    NetkeibaRaceResult,
    NetkeibaResultEntry,
    OddsEntry,
    PayoutEntry,
    RaceCard,
    RaceOdds,
    RaceResult,
    ResultEntry,
    Runner,
)


def _write_pre_race_timeline_fixture(store: AnalysisSQLiteStore) -> str:
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
            runners=[
                Runner(horse_no="10", frame_no="5", horse_name="Ten"),
                Runner(horse_no="2", frame_no="1", horse_name="Two"),
            ],
            fetched_at=datetime.fromisoformat("2026-07-18T14:55:00+09:00"),
            source="jra",
        ),
    )
    snapshots = [
        (
            "t_minus_30m",
            "2026-07-18T15:05:02+09:00",
            "win",
            [OddsEntry(bet_type="win", combination=["1"], odds="3.2", popularity="2")],
        ),
        (
            "t_minus_30m",
            "2026-07-18T15:05:03+09:00",
            "wide",
            [
                OddsEntry(bet_type="wide", combination=["4", "10"], odds="8.8", popularity="3"),
                OddsEntry(bet_type="wide", combination=["1", "2"], odds="12.0"),
            ],
        ),
        (
            "t_minus_10m",
            "2026-07-18T15:25:02+09:00",
            "win",
            [OddsEntry(bet_type="win", combination=["1"], odds="3.0", popularity="2")],
        ),
        (
            "t_minus_10m",
            "2026-07-18T15:25:03+09:00",
            "wide",
            [OddsEntry(bet_type="wide", combination=["4", "10"], odds="8.5", popularity="3")],
        ),
        (
            "t_minus_10m",
            "2026-07-18T15:25:04+09:00",
            "exacta",
            [OddsEntry(bet_type="exacta", combination=["4", "10"], odds="18.0", popularity="4")],
        ),
        (
            "t_minus_2m",
            "2026-07-18T15:33:02+09:00",
            "win",
            [OddsEntry(bet_type="win", combination=["1"], odds="2.8", popularity="1")],
        ),
        (
            "t_minus_2m",
            "2026-07-18T15:33:03+09:00",
            "wide",
            [OddsEntry(bet_type="wide", combination=["2", "9"], odds="7.0")],
        ),
    ]
    for odds_timing, fetched_at, bet_type, entries in snapshots:
        store.write_odds(
            RaceOdds(
                race_id=race_id,
                bet_type=bet_type,
                entries=entries,
                fetched_at=datetime.fromisoformat(fetched_at),
                source="jra",
            ),
            bet_type=bet_type,
            odds_timing=odds_timing,
        )
    return race_id


def _save_live_shadow_observation(
    store: AnalysisSQLiteStore,
    *,
    run_id: str,
    observed_at: datetime,
    win_odds: str,
) -> None:
    race_id = "202607180211"
    entry = JraDayRaceScoutEntry(
        race_id=race_id,
        course="kokura",
        race_no=11,
        race_name="テスト競走",
        start_time="15:35",
        grade="A",
    )
    result = JraDayRaceScoutResult(
        run_id=run_id,
        date=date(2026, 7, 18),
        observed_at=observed_at,
        status="completed",
        race_count=1,
        analyzed_count=1,
        candidates=[entry],
        entries=[entry],
    )
    decision = {
        "source_status": "recommended",
        "status": "shadow_only",
        "ticket_status": "shadow_only",
        "policy_version": "policy-v1",
        "tickets": [],
        "candidates": [{"horse_no": "5", "win_odds": float(win_odds)}],
    }
    observation = JraLiveShadowObservation(
        observation_id=f"{run_id}:{race_id}",
        run_id=run_id,
        race_id=race_id,
        race_date=date(2026, 7, 18),
        course="kokura",
        race_no=11,
        observed_at=observed_at,
        model_version="model-v2",
        model_created_at=datetime(2026, 7, 16, tzinfo=UTC),
        trained_through=date(2026, 7, 11),
        policy_version="policy-v1",
        decision_status="shadow_only",
        ticket_status="shadow_only",
        odds=RaceOdds(
            race_id=race_id,
            bet_type="win",
            entries=[OddsEntry(bet_type="win", combination=["5"], odds=win_odds)],
            fetched_at=observed_at,
            source="jra",
        ),
        materials_ranking=[{"horse_no": "5"}],
        history_ranking=[{"horse_no": "5", "win_probability_race_normalized": 0.25}],
        decision=decision,
        component_status={"odds": "fresh"},
    )
    store.save_jra_scout_result(result, observations=[observation])


def test_analysis_store_creates_schema(tmp_path):
    path = tmp_path / "analysis.sqlite"
    AnalysisSQLiteStore(path)

    with sqlite3.connect(path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }

    assert "races" in tables
    assert "odds_entries" in tables
    assert "predictions" in tables
    assert "evaluations" in tables
    assert "netkeiba_race_results" in tables
    assert "netkeiba_result_entries" in tables
    assert "netkeiba_payouts" in tables
    assert "netkeiba_odds_entries" in tables
    assert "netkeiba_race_mappings" in tables
    assert "bet_records" in tables
    assert "bet_record_tickets" in tables
    assert "bet_record_results" in tables
    assert "daily_prediction_log_imports" in tables
    assert "daily_prediction_log_entries" in tables
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("pragma table_info(races)").fetchall()}
    assert "meeting_no" in columns
    assert "meeting_day" in columns


def test_analysis_store_replaces_daily_prediction_log_entries_and_resolves_race_id(tmp_path):
    path = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(path)
    race = MeetingRace(race_no=11, race_id="2026070821040311", race_name="Sample", start_time="20:10")
    store.write_race(date(2026, 7, 8), "kawasaki", race, source="meeting", fetched_at=datetime.now(UTC))

    result = store.replace_daily_prediction_log_entries(
        source_path="notes/2026-07-08_kawasaki_predictions.md",
        log_date="2026-07-08",
        venue="川崎",
        entries=[
            {
                "entry_timestamp": datetime(2026, 7, 8, 19, 55, 30),
                "entry_type": "事前予想",
                "race_date": "2026-07-08",
                "course": "kawasaki",
                "race_no": 11,
                "topic": "川崎 11R Sample",
                "prediction_mode": "総合買い目型",
                "payload": {"対象": "川崎 11R Sample"},
                "raw_markdown": "### 2026-07-08 19:55:30\n- 種別: 事前予想",
            }
        ],
    )

    assert result["imported_entries"] == 1
    assert result["resolved_race_ids"] == 1

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("select race_id, course, race_no from daily_prediction_log_entries").fetchone()

    assert row["race_id"] == "2026070821040311"
    assert row["course"] == "kawasaki"
    assert row["race_no"] == 11


def test_analysis_store_writes_pre_race_and_result_data_without_leaking_result_to_snapshot(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    race = MeetingRace(race_no=11, race_id="202603220611", race_name="Chiba Stakes", start_time="15:45")
    store.write_race(date(2026, 3, 22), "nakayama", race, source="meeting", fetched_at=datetime.now(UTC))
    store.write_card(
        date(2026, 3, 22),
        "nakayama",
        11,
        RaceCard(
            race_id="202603220611",
            race_name="Chiba Stakes",
            course="nakayama",
            distance="1200",
            surface="dirt",
            start_time="15:45",
            runners=[
                Runner(
                    frame_no="1",
                    horse_no="1",
                    horse_name="Dragon Wells",
                    jockey="Jockey",
                    odds="12.4",
                    popularity="5",
                )
            ],
            fetched_at=datetime.now(UTC),
            source="card",
        ),
    )
    store.write_odds(
        RaceOdds(
            race_id="202603220611",
            bet_type="wide",
            entries=[
                OddsEntry(
                    bet_type="wide",
                    combination=["1", "2"],
                    odds="16.1",
                    popularity="8",
                )
            ],
            fetched_at=datetime.now(UTC),
            source="odds",
        ),
        bet_type="wide",
    )
    store.write_result(
        RaceResult(
            race_id="202603220611",
            race_name="Chiba Stakes",
            results=[
                ResultEntry(rank="1", horse_no="1", horse_name="Dragon Wells", jockey="Jockey", time="1:10.0")
            ],
            payouts=[PayoutEntry(bet_type="wide", combination="1-2", payout="1,610", popularity="8")],
            fetched_at=datetime.now(UTC),
            source="result",
        )
    )

    snapshot = store.get_pre_race_snapshot("202603220611")

    assert snapshot.race.race_id == "202603220611"
    assert snapshot.runners[0].horse_name == "Dragon Wells"
    assert snapshot.runners[0].card_odds == 12.4
    assert snapshot.odds[0].entries[0].odds == 16.1
    assert not hasattr(snapshot, "results")
    assert not hasattr(snapshot, "payouts")
    assert store.count_rows("result_entries") == 1
    assert store.count_rows("payouts") == 1
    assert store.has_card("202603220611") is True
    assert store.has_result("202603220611") is True
    assert store.has_odds_snapshot("202603220611", "wide") is True


def test_analysis_store_reads_latest_and_selected_pre_race_snapshots(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    race_id = _write_pre_race_timeline_fixture(store)

    latest = store.get_pre_race_snapshot(race_id)

    assert latest.race.race_date == date(2026, 7, 18)
    assert latest.race.fetched_at == datetime.fromisoformat("2026-07-18T14:55:00+09:00")
    assert [runner.horse_no for runner in latest.runners] == ["2", "10"]
    assert [snapshot.bet_type for snapshot in latest.odds] == ["exacta", "wide", "win"]
    assert {
        snapshot.bet_type: snapshot.odds_timing
        for snapshot in latest.odds
    } == {
        "exacta": "t_minus_10m",
        "wide": "t_minus_2m",
        "win": "t_minus_2m",
    }
    assert latest.meta.available_odds_timings == [
        "t_minus_30m",
        "t_minus_10m",
        "t_minus_2m",
    ]
    assert latest.meta.missing_components == []

    selected = store.get_pre_race_snapshot(race_id, odds_timing="t_minus_10m")

    assert [snapshot.bet_type for snapshot in selected.odds] == ["exacta", "wide", "win"]
    assert all(snapshot.odds_timing == "t_minus_10m" for snapshot in selected.odds)
    assert selected.meta.requested_odds_timing == "t_minus_10m"


def test_analysis_store_can_skip_odds_in_pre_race_snapshot(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    race_id = _write_pre_race_timeline_fixture(store)

    snapshot = store.get_pre_race_snapshot(
        race_id,
        include_odds=False,
        odds_timing="t_minus_10m",
    )

    assert snapshot.odds == []
    assert snapshot.meta.available_odds_timings == []
    assert snapshot.meta.missing_components == []


def test_analysis_store_reads_odds_timeline_with_combination_normalization(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    race_id = _write_pre_race_timeline_fixture(store)

    wide = store.get_odds_timeline(race_id, "wide", ["10", "4"])

    assert wide.combination == ["4", "10"]
    assert wide.total == 3
    assert [snapshot.odds_timing for snapshot in wide.snapshots] == [
        "t_minus_30m",
        "t_minus_10m",
        "t_minus_2m",
    ]
    assert [snapshot.entries[0].odds for snapshot in wide.snapshots[:2]] == [8.8, 8.5]
    assert wide.snapshots[2].entries == []

    all_wide = store.get_odds_timeline(race_id, "wide")
    assert [entry.combination for entry in all_wide.snapshots[0].entries] == [
        ["4", "10"],
        ["1", "2"],
    ]

    exacta_forward = store.get_odds_timeline(race_id, "exacta", ["4", "10"])
    exacta_reverse = store.get_odds_timeline(race_id, "exacta", ["10", "4"])
    assert len(exacta_forward.snapshots[0].entries) == 1
    assert exacta_reverse.snapshots[0].entries == []


def test_analysis_store_appends_same_timing_and_snapshot_returns_latest_generation(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    race_id = _write_pre_race_timeline_fixture(store)
    store.write_odds(
        RaceOdds(
            race_id=race_id,
            bet_type="wide",
            entries=[
                OddsEntry(
                    bet_type="wide",
                    combination=["4", "10"],
                    odds="8.2",
                    popularity="2",
                )
            ],
            fetched_at=datetime.fromisoformat("2026-07-18T15:26:03+09:00"),
            source="jra-refresh",
        ),
        bet_type="wide",
        odds_timing="t_minus_10m",
    )

    timeline = store.get_odds_timeline(race_id, "wide")
    snapshot = store.get_pre_race_snapshot(
        race_id,
        odds_timing="t_minus_10m",
    )
    selected_wide = [item for item in snapshot.odds if item.bet_type == "wide"]

    assert timeline.total == 4
    assert [item.odds_timing for item in timeline.snapshots] == [
        "t_minus_30m",
        "t_minus_10m",
        "t_minus_10m",
        "t_minus_2m",
    ]
    assert len(selected_wide) == 1
    assert selected_wide[0].source == "jra-refresh"
    assert selected_wide[0].entries[0].odds == 8.2


def test_analysis_store_odds_timeline_handles_empty_not_found_and_invalid_combination(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    race_id = _write_pre_race_timeline_fixture(store)
    empty_race_id = "202607180212"
    store.write_race(
        date(2026, 7, 18),
        "kokura",
        MeetingRace(
            race_no=12,
            race_id=empty_race_id,
            race_name="Empty Stakes",
            start_time="16:10",
        ),
        source="jra",
        fetched_at=datetime.fromisoformat("2026-07-18T15:00:00+09:00"),
    )

    empty = store.get_odds_timeline(race_id, "trifecta")
    empty_snapshot = store.get_pre_race_snapshot(empty_race_id)

    assert empty.snapshots == []
    assert empty.total == 0
    assert empty_snapshot.runners == []
    assert empty_snapshot.odds == []
    assert empty_snapshot.meta.missing_components == ["runners", "odds"]
    with pytest.raises(BadRequestError):
        store.get_odds_timeline(race_id, "wide", ["4"])
    with pytest.raises(LookupError):
        store.get_pre_race_snapshot("202607180213")
    with pytest.raises(LookupError):
        store.get_odds_timeline("202607180213", "wide")


def test_analysis_store_saves_and_lists_live_shadow_observations_by_run(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    first = datetime(2026, 7, 18, 5, 0, tzinfo=UTC)
    first_updated = datetime(2026, 7, 18, 5, 5, tzinfo=UTC)
    second = datetime(2026, 7, 18, 5, 10, tzinfo=UTC)

    _save_live_shadow_observation(
        store,
        run_id="jra-scout-1",
        observed_at=first,
        win_odds="4.0",
    )
    _save_live_shadow_observation(
        store,
        run_id="jra-scout-1",
        observed_at=first_updated,
        win_odds="3.8",
    )
    _save_live_shadow_observation(
        store,
        run_id="jra-scout-2",
        observed_at=second,
        win_odds="3.5",
    )

    newest = store.list_jra_live_shadow_observations(
        "202607180211",
        limit=1,
        offset=0,
    )
    older = store.list_jra_live_shadow_observations(
        "202607180211",
        limit=1,
        offset=1,
    )

    assert store.count_rows("jra_live_shadow_observations") == 2
    assert newest.total == 2
    assert newest.items[0].run_id == "jra-scout-2"
    assert newest.items[0].observed_at == newest.items[0].odds.fetched_at
    assert newest.items[0].decision["tickets"] == []
    assert newest.items[0].decision["source_status"] == "recommended"
    assert older.items[0].run_id == "jra-scout-1"
    assert older.items[0].odds.entries[0].odds == "3.8"


def test_analysis_store_live_shadow_observations_reject_unknown_race(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")

    with pytest.raises(LookupError):
        store.list_jra_live_shadow_observations("202607180299")


def test_analysis_store_upserts_card_and_appends_odds_snapshots(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    card = RaceCard(
        race_id="202603220611",
        race_name="Chiba Stakes",
        course="nakayama",
        runners=[Runner(horse_no="1", horse_name="Dragon Wells")],
        fetched_at=datetime.now(UTC),
        source="card",
    )
    odds = RaceOdds(
        race_id="202603220611",
        bet_type="wide",
        entries=[OddsEntry(combination=["1", "2"], odds="16.1", popularity="8")],
        fetched_at=datetime.now(UTC),
        source="odds",
    )

    store.write_card(date(2026, 3, 22), "nakayama", 11, card)
    store.write_card(date(2026, 3, 22), "nakayama", 11, card)
    store.write_odds(odds, bet_type="wide")
    store.write_odds(odds, bet_type="wide")

    assert store.count_rows("runners") == 1
    assert store.count_rows("odds_snapshots") == 2
    assert store.count_rows("odds_entries") == 2


def test_analysis_store_migrates_legacy_odds_snapshot_unique_constraint(tmp_path):
    path = tmp_path / "analysis.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            create table odds_snapshots (
                snapshot_id text primary key,
                race_id text not null,
                bet_type text not null,
                odds_timing text not null,
                fetched_at text not null,
                source text not null,
                unique (race_id, bet_type, odds_timing)
            );
            create table odds_entries (
                snapshot_id text not null,
                race_id text not null,
                bet_type text not null,
                combination text not null,
                combination_json text not null,
                odds real,
                odds_min real,
                odds_max real,
                popularity integer
            );
            insert into odds_snapshots
            values ('legacy-id', '202603220611', 'wide', 't_minus_10m',
                    '2026-03-22T15:20:00+00:00', 'legacy');
            insert into odds_entries
            values ('legacy-id', '202603220611', 'wide', '1-2', '["1", "2"]',
                    16.1, null, null, 8);
            """
        )

    store = AnalysisSQLiteStore(path)
    store.write_odds(
        RaceOdds(
            race_id="202603220611",
            bet_type="wide",
            entries=[OddsEntry(combination=["1", "2"], odds="15.8", popularity="7")],
            fetched_at=datetime(2026, 3, 22, 15, 21, tzinfo=UTC),
            source="refresh",
        ),
        bet_type="wide",
        odds_timing="t_minus_10m",
    )
    AnalysisSQLiteStore(path)

    with sqlite3.connect(path) as conn:
        snapshot_ids = [
            row[0]
            for row in conn.execute(
                "select snapshot_id from odds_snapshots order by fetched_at"
            ).fetchall()
        ]
        unique_indexes = [
            row
            for row in conn.execute("pragma index_list(odds_snapshots)").fetchall()
            if row[2]
        ]

    assert snapshot_ids[0] == "legacy-id"
    assert len(snapshot_ids) == 2
    assert store.count_rows("odds_entries") == 2
    assert all(index[1].startswith("sqlite_autoindex") for index in unique_indexes)


def test_analysis_store_extracts_meeting_fields_from_16_digit_race_id(tmp_path):
    path = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(path)
    race = MeetingRace(race_no=1, race_id="2026070419040501", race_name="Sample", start_time="15:00")
    card = RaceCard(
        race_id="2026070419040501",
        race_name="Sample",
        course="funabashi",
        runners=[Runner(horse_no="1", horse_name="Runner")],
        fetched_at=datetime.now(UTC),
        source="card",
    )

    store.write_race(date(2026, 7, 4), "funabashi", race, source="meeting", fetched_at=datetime.now(UTC))
    store.write_card(date(2026, 7, 4), "funabashi", 1, card)

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("select meeting_no, meeting_day from races where race_id = ?", ("2026070419040501",)).fetchone()

    assert row["meeting_no"] == 4
    assert row["meeting_day"] == 5


def test_analysis_store_writes_netkeiba_result_and_odds(tmp_path):
    path = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(path)
    result = NetkeibaRaceResult(
        race_id="202605021211",
        race_name="Tokyo Race",
        date="2026-05-02",
        course="Tokyo",
        race_no="11",
        surface="芝",
        distance="2400",
        direction="左",
        weather="晴",
        track_condition="良",
        results=[
            NetkeibaResultEntry(
                rank="1",
                frame_no="8",
                horse_no="17",
                horse_name="Sample Horse",
                sex_age="牡3",
                weight_carried="57.0",
                jockey="Sample Jockey",
                trainer="Sample Trainer",
                horse_weight="500",
                horse_weight_diff="-2",
                finish_time="2:23.1",
                margin="",
                corner_order="3-3-3-2",
                final_3f="33.4",
                win_odds="5.6",
                popularity="2",
            )
        ],
        payouts=[PayoutEntry(bet_type="wide", combination="13-17", payout="1,610", popularity="8")],
        corner_passages=["3-3-3-2"],
        fetched_at=datetime.now(UTC),
        source="netkeiba-fixture",
    )
    odds = RaceOdds(
        race_id="202605021211",
        bet_type="wide",
        entries=[
            OddsEntry(
                bet_type="wide",
                combination=["13", "17"],
                odds_min="16.1",
                odds_max="17.3",
                popularity="8",
            )
        ],
        fetched_at=datetime.now(UTC),
        source="netkeiba-fixture",
    )

    store.write_netkeiba_result(result, jra_race_id="202606280301")
    store.write_netkeiba_odds(odds, jra_race_id="202606280301", bet_type="wide")

    assert store.has_netkeiba_result("202605021211") is True
    assert store.has_netkeiba_odds_entry("202605021211", "wide", ["13", "17"]) is True
    assert store.has_netkeiba_odds_entry("202605021211", "wide", ["013", "017"]) is True
    assert store.count_rows("netkeiba_race_results") == 1
    assert store.count_rows("netkeiba_result_entries") == 1
    assert store.count_rows("netkeiba_payouts") == 1
    assert store.count_rows("netkeiba_odds_entries") == 1

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        race = conn.execute("select * from netkeiba_race_results").fetchone()
        entry = conn.execute("select * from netkeiba_result_entries").fetchone()
        payout = conn.execute("select * from netkeiba_payouts").fetchone()
        stored_odds = conn.execute("select * from netkeiba_odds_entries").fetchone()

    assert race["jra_race_id"] == "202606280301"
    assert race["netkeiba_race_id"] == "202605021211"
    assert entry["horse_weight_diff"] == -2
    assert entry["final_3f"] == 33.4
    assert entry["win_odds"] == 5.6
    assert entry["popularity"] == 2
    assert payout["payout"] == 1610
    assert stored_odds["combination"] == "13-17"
    assert stored_odds["odds_min"] == 16.1


def test_analysis_store_treats_incomplete_netkeiba_result_as_missing(tmp_path):
    path = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(path)

    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            insert into netkeiba_race_results
            (netkeiba_race_id, jra_race_id, source, fetched_at)
            values (?, ?, ?, ?)
            """,
            ("202605021211", "202606280301", "fixture", datetime.now(UTC).isoformat()),
        )

    assert store.has_netkeiba_result("202605021211") is False


def test_analysis_store_upserts_and_lists_netkeiba_race_mappings(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    store.write_netkeiba_race_mappings(
        [
            {
                "jra_race_id": "202605020511",
                "netkeiba_race_id": "202605010111",
                "race_date": "2026-05-02",
                "course": "tokyo",
                "race_no": "11",
                "mapping_status": "mapped_estimated",
                "mapping_note": "first",
            },
            {
                "jra_race_id": "202605020512",
                "netkeiba_race_id": "",
                "race_date": "2026-05-02",
                "course": "tokyo",
                "race_no": "12",
                "mapping_status": "unmapped",
                "mapping_note": "no calendar",
            },
        ]
    )
    store.write_netkeiba_race_mappings(
        [
            {
                "jra_race_id": "202605020511",
                "netkeiba_race_id": "202605040111",
                "race_date": "2026-05-02",
                "course": "tokyo",
                "race_no": "11",
                "mapping_status": "mapped",
                "mapping_note": "updated",
            }
        ]
    )

    mappings = store.list_netkeiba_race_mappings(date(2026, 5, 1), date(2026, 5, 31))

    assert store.count_rows("netkeiba_race_mappings") == 2
    assert mappings[0]["jra_race_id"] == "202605020511"
    assert mappings[0]["netkeiba_race_id"] == "202605040111"
    assert mappings[0]["mapping_status"] == "mapped"
    assert mappings[0]["mapping_note"] == "updated"
    assert mappings[1]["mapping_status"] == "unmapped"


def test_analysis_store_records_collection_error(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    store.write_error(
        run_id="run-1",
        target_date=date(2026, 3, 22),
        course="nakayama",
        stage="result",
        exc=LookupError("payout block not found"),
        race_id="202603220611",
        race_no=11,
    )

    assert store.count_rows("collection_errors") == 1


def test_analysis_store_creates_bet_record_with_box_expansion(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")

    record = store.create_bet_record(
        BetRecordCreateRequest.model_validate(
            {
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
                        "mode": "normal",
                        "selection": ["2", "4", "10"],
                        "amount": 100,
                    },
                ],
            }
        )
    )

    assert record.total_amount == 400
    assert [ticket.selection for ticket in record.tickets] == ["2-4", "2-10", "4-10", "2-4-10"]
    assert [ticket.is_box_expanded for ticket in record.tickets] == [True, True, True, False]
    assert store.count_rows("bet_records") == 1
    assert store.count_rows("bet_record_tickets") == 4


def test_analysis_store_upserts_prediction_record_with_race_context(tmp_path):
    path = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(path)

    result = store.upsert_prediction_record(
        {
            "prediction_id": "pred-1",
            "race_id": "2026070921040410",
            "theory_version": "assistant:v1",
            "mode": "integrated_betting",
            "budget": 1000,
            "pre_race_snapshot": {
                "date": "2026-07-09",
                "course": "kawasaki",
                "race_no": 10,
                "meeting_no": 4,
                "meeting_day": 4,
                "card": {
                    "race_id": "2026070921040410",
                    "race_name": "江戸切子特別",
                    "course": "kawasaki",
                    "distance": "1400",
                    "surface": "dirt",
                    "start_time": "19:40",
                    "source": "card",
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "runners": [
                        {"horse_no": "6", "horse_name": "ダンデライオン", "frame_no": "6"},
                        {"horse_no": "10", "horse_name": "ナリノエンブレム", "frame_no": "8"},
                    ],
                },
            },
            "prediction_json": {
                "predicted_top3": [
                    {"horse_no": "6", "horse_name": "ダンデライオン", "odds": 1.4, "role": "head_axis"},
                    {"horse_no": "10", "horse_name": "ナリノエンブレム", "odds": 6.4},
                    {"horse_no": "11", "horse_name": "トンボ", "odds": 14.2},
                ]
            },
            "prediction_tickets": [
                {"ticket_id": "pt-1", "bucket": "core", "bet_type": "quinella", "selection": ["6", "10"], "amount": 500},
                {"ticket_id": "pt-2", "bucket": "reserve", "bet_type": "wide", "selection": "11-6", "amount": 500},
            ],
        }
    )

    assert result["predictions"] == 1
    assert result["prediction_tickets"] == 2
    assert store.count_rows("races") == 1
    assert store.count_rows("runners") == 2

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        race = conn.execute("select race_date, course, race_no, meeting_no, meeting_day from races where race_id = ?", ("2026070921040410",)).fetchone()
        ticket = conn.execute("select selection from prediction_tickets where ticket_id = ?", ("pt-2",)).fetchone()

    assert race["race_date"] == "2026-07-09"
    assert race["course"] == "kawasaki"
    assert race["race_no"] == 10
    assert race["meeting_no"] == 4
    assert race["meeting_day"] == 4
    assert ticket["selection"] == "6-11"


def test_analysis_store_evaluates_prediction_record_from_saved_tickets_and_payouts(tmp_path):
    path = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(path)
    store.upsert_prediction_record(
        {
            "prediction_id": "pred-1",
            "race_id": "2026070921040410",
            "theory_version": "assistant:v1",
            "mode": "integrated_betting",
            "budget": 1000,
            "pre_race_snapshot": {
                "date": "2026-07-09",
                "course": "kawasaki",
                "race_no": 10,
                "meeting_no": 4,
                "meeting_day": 4,
            },
            "prediction_json": {
                "predicted_top3": [
                    {"horse_no": "6", "horse_name": "ダンデライオン", "odds": 1.4, "role": "head_axis"},
                    {"horse_no": "7", "horse_name": "ラムテリオス", "odds": 21.6},
                    {"horse_no": "5", "horse_name": "エムティワイザー", "odds": 12.4},
                ],
                "middle_hole_candidates": [{"horse_no": "7", "horse_name": "ラムテリオス", "odds": 21.6}],
            },
            "prediction_tickets": [
                {"ticket_id": "pt-1", "bucket": "core", "bet_type": "wide", "selection": ["5", "7"], "amount": 500},
                {"ticket_id": "pt-2", "bucket": "reserve", "bet_type": "quinella", "selection": ["6", "10"], "amount": 500},
            ],
        }
    )
    store.write_result(
        RaceResult(
            race_id="2026070921040410",
            race_name="江戸切子特別",
            results=[
                ResultEntry(rank="1", horse_no="7", horse_name="ラムテリオス", jockey="佐野遥久", time="1:30.8"),
                ResultEntry(rank="2", horse_no="3", horse_name="ボニーマジェスティ", jockey="櫻井光輔", time="1:31.0"),
                ResultEntry(rank="3", horse_no="5", horse_name="エムティワイザー", jockey="古岡勇樹", time="1:31.1"),
            ],
            payouts=[
                PayoutEntry(bet_type="wide", combination="5-7", payout="1090", popularity="13"),
                PayoutEntry(bet_type="quinella", combination="3-7", payout="27310", popularity="38"),
            ],
            fetched_at=datetime.now(UTC),
            source="result",
        )
    )

    result = store.evaluate_prediction_record(
        {
            "prediction_id": "pred-1",
            "evaluation_id": "eval-1",
            "review_notes": ["会話予想を保存後に評価"],
        }
    )

    assert result["evaluations"] == 1
    assert result["evaluation_ticket_results"] == 2
    assert result["total_bet"] == 1000
    assert result["total_payout"] == 5450
    assert result["hit"] is True

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        evaluation = conn.execute(
            "select total_bet, total_payout, hit, gami, axis_in_top3, middle_hole_in_top3 from evaluations where evaluation_id = ?",
            ("eval-1",),
        ).fetchone()
        ticket_rows = conn.execute(
            "select selection, payout, hit from evaluation_ticket_results where evaluation_id = ? order by selection",
            ("eval-1",),
        ).fetchall()

    assert evaluation["total_bet"] == 1000
    assert evaluation["total_payout"] == 5450
    assert evaluation["hit"] == 1
    assert evaluation["gami"] == 0
    assert evaluation["axis_in_top3"] == 0
    assert evaluation["middle_hole_in_top3"] == 1
    assert [(row["selection"], row["payout"], row["hit"]) for row in ticket_rows] == [("5-7", 5450, 1), ("6-10", 0, 0)]


def test_analysis_store_scales_payout_by_ticket_amount_when_evaluating_prediction(tmp_path):
    path = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(path)
    store.upsert_prediction_record(
        {
            "prediction_id": "pred-1",
            "race_id": "2026070921040410",
            "theory_version": "assistant:v1",
            "mode": "integrated_betting",
            "budget": 200,
            "pre_race_snapshot": {
                "date": "2026-07-09",
                "course": "kawasaki",
                "race_no": 10,
                "meeting_no": 4,
                "meeting_day": 4,
            },
            "prediction_json": {
                "predicted_top3": [
                    {"horse_no": "7", "horse_name": "Ramterios", "odds": 21.6, "role": "head_axis"},
                    {"horse_no": "3", "horse_name": "Bonnie Majesty", "odds": 41.3},
                    {"horse_no": "5", "horse_name": "MT Wiser", "odds": 12.4},
                ]
            },
            "prediction_tickets": [
                {"ticket_id": "pt-1", "bucket": "core", "bet_type": "wide", "selection": ["5", "7"], "amount": 200},
            ],
        }
    )
    store.write_result(
        RaceResult(
            race_id="2026070921040410",
            race_name="Sample",
            results=[
                ResultEntry(rank="1", horse_no="7", horse_name="Ramterios", jockey="Jockey A", time="1:30.8"),
                ResultEntry(rank="2", horse_no="3", horse_name="Bonnie Majesty", jockey="Jockey B", time="1:31.0"),
                ResultEntry(rank="3", horse_no="5", horse_name="MT Wiser", jockey="Jockey C", time="1:31.1"),
            ],
            payouts=[PayoutEntry(bet_type="wide", combination="5-7", payout="1090", popularity="13")],
            fetched_at=datetime.now(UTC),
            source="result",
        )
    )

    result = store.evaluate_prediction_record({"prediction_id": "pred-1", "evaluation_id": "eval-1"})

    assert result["total_bet"] == 200
    assert result["total_payout"] == 2180
    assert result["return_rate"] == 10.9


def test_analysis_store_creates_bet_record_with_16_digit_nankan_race_id(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")

    record = store.create_bet_record(
        BetRecordCreateRequest.model_validate(
            {
                "race_id": "2026070419040501",
                "decision_source": "manual",
                "total_amount": 100,
                "tickets": [{"bet_type": "win", "selection": ["1"], "amount": 100}],
            }
        )
    )
    listed = store.list_bet_records(race_id="2026070419040501")

    assert record.race_id == "2026070419040501"
    assert record.tickets[0].race_id == "2026070419040501"
    assert listed.total == 1
    assert listed.items[0].bet_record_id == record.bet_record_id


def test_bet_record_create_request_rejects_invalid_race_id_lengths():
    for race_id in ("20260705101", "202607041904050", "race20260704"):
        with pytest.raises(ValueError):
            BetRecordCreateRequest.model_validate(
                {
                    "race_id": race_id,
                    "decision_source": "manual",
                    "total_amount": 100,
                    "tickets": [{"bet_type": "win", "selection": ["1"], "amount": 100}],
                }
            )


def test_analysis_store_gets_bet_record_with_prediction_link(tmp_path):
    path = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(path)
    record = store.create_bet_record(
        BetRecordCreateRequest.model_validate(
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
    )

    with sqlite3.connect(path) as conn:
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

    loaded = store.get_bet_record(record.bet_record_id)

    assert loaded.prediction is not None
    assert loaded.prediction["prediction_id"] == "pred-1"
    assert loaded.prediction_tickets[0]["ticket_id"] == "pt-1"
    assert loaded.tickets[0].prediction_ticket_id == "pt-1"


def test_analysis_store_settles_all_miss_to_zero_payout(tmp_path):
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
        BetRecordCreateRequest.model_validate(
            {
                "race_id": "202607051011",
                "decision_source": "manual",
                "total_amount": 400,
                "tickets": [
                    {"bet_type": "wide", "mode": "box", "selection": ["2", "4", "10"], "amount_per_ticket": 100},
                    {"bet_type": "trio", "mode": "normal", "selection": ["2", "4", "10"], "amount": 100},
                ],
            }
        )
    )

    settlement = store.settle_bet_record(record.bet_record_id)

    assert settlement.total_bet == 400
    assert settlement.total_payout == 0
    assert settlement.hit is False
    assert all(ticket.hit is False and ticket.payout == 0 for ticket in settlement.ticket_results)
    assert store.count_rows("bet_record_results") == 1


def test_analysis_store_settles_16_digit_nankan_race_id(tmp_path):
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
        BetRecordCreateRequest.model_validate(
            {
                "race_id": "2026070419040501",
                "decision_source": "manual",
                "total_amount": 100,
                "tickets": [{"bet_type": "win", "selection": ["1"], "amount": 100}],
            }
        )
    )

    settlement = store.settle_bet_record(record.bet_record_id)
    loaded = store.get_bet_record(record.bet_record_id)

    assert settlement.race_id == "2026070419040501"
    assert settlement.total_payout == 1830
    assert settlement.hit is True
    assert loaded.result is not None
    assert loaded.result.race_id == "2026070419040501"


def test_analysis_store_settles_unordered_bet_type_with_normalized_match(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    store.write_result(
        RaceResult(
            race_id="202607051011",
            race_name="Kitakyushu Kinen",
            results=[],
            payouts=[PayoutEntry(bet_type="wide", combination="10-2", payout="1,610")],
            fetched_at=datetime.now(UTC),
            source="result",
        )
    )
    record = store.create_bet_record(
        BetRecordCreateRequest.model_validate(
            {
                "race_id": "202607051011",
                "decision_source": "manual",
                "total_amount": 100,
                "tickets": [{"bet_type": "wide", "selection": ["2", "10"], "amount": 100}],
            }
        )
    )

    settlement = store.settle_bet_record(record.bet_record_id)

    assert settlement.hit is True
    assert settlement.total_payout == 1610
    assert settlement.ticket_results[0].selection == "2-10"
    assert settlement.ticket_results[0].payout == 1610


def test_analysis_store_scales_payout_by_ticket_amount_when_settling(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    store.write_result(
        RaceResult(
            race_id="202607051011",
            race_name="Kitakyushu Kinen",
            results=[],
            payouts=[PayoutEntry(bet_type="wide", combination="10-2", payout="1610")],
            fetched_at=datetime.now(UTC),
            source="result",
        )
    )
    record = store.create_bet_record(
        BetRecordCreateRequest.model_validate(
            {
                "race_id": "202607051011",
                "decision_source": "manual",
                "total_amount": 200,
                "tickets": [{"bet_type": "wide", "selection": ["2", "10"], "amount": 200}],
            }
        )
    )

    settlement = store.settle_bet_record(record.bet_record_id)

    assert settlement.total_payout == 3220
    assert settlement.ticket_results[0].payout == 3220


def test_analysis_store_settles_ordered_bet_types_with_order_preserved(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    store.write_result(
        RaceResult(
            race_id="202607051011",
            race_name="Kitakyushu Kinen",
            results=[],
            payouts=[
                PayoutEntry(bet_type="馬単", combination="1-2", payout="900"),
                PayoutEntry(bet_type="3連単", combination="1-2-3", payout="2,400"),
            ],
            fetched_at=datetime.now(UTC),
            source="result",
        )
    )
    record = store.create_bet_record(
        BetRecordCreateRequest.model_validate(
            {
                "race_id": "202607051011",
                "decision_source": "manual",
                "total_amount": 200,
                "tickets": [
                    {"bet_type": "exacta", "selection": ["1", "2"], "amount": 100},
                    {"bet_type": "trifecta", "selection": ["1", "3", "2"], "amount": 100},
                ],
            }
        )
    )

    settlement = store.settle_bet_record(record.bet_record_id)

    assert settlement.total_payout == 900
    assert settlement.ticket_results[0].hit is True
    assert settlement.ticket_results[0].payout == 900
    assert settlement.ticket_results[1].selection == "1-3-2"
    assert settlement.ticket_results[1].hit is False
    assert settlement.ticket_results[1].payout == 0


def test_analysis_store_rejects_invalid_count_table(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")

    with pytest.raises(ValueError):
        store.count_rows("races; drop table races")


def test_analysis_store_reads_and_lists_prediction_records(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    store.upsert_prediction_record(
        {
            "prediction_id": "pred-read-1",
            "race_id": "202607051011",
            "theory_version": "v-read",
            "mode": "integrated",
            "budget": 1000,
            "pre_race_snapshot": {
                "date": "2026-07-05",
                "course": "kokura",
                "race_no": 11,
            },
            "prediction_json": {"axis": "2"},
            "prediction_tickets": [
                {
                    "ticket_id": "pt-read-1",
                    "bucket": "core",
                    "bet_type": "wide",
                    "selection": ["2", "10"],
                    "amount": 500,
                    "reason": "read test",
                }
            ],
        }
    )

    record = store.get_prediction_record("pred-read-1")
    page = store.list_prediction_records(
        from_date=date(2026, 7, 5),
        to_date=date(2026, 7, 5),
        theory_version="v-read",
        mode="integrated",
        limit=10,
        offset=0,
    )

    assert record.pre_race_snapshot["course"] == "kokura"
    assert record.prediction == {"axis": "2"}
    assert record.prediction_tickets[0].selection_json == ["2", "10"]
    assert page.total == 1
    assert page.items[0].prediction_id == "pred-read-1"
    with pytest.raises(LookupError):
        store.get_prediction_record("missing")


def test_analysis_store_reads_lists_and_summarizes_evaluations(tmp_path):
    path = tmp_path / "analysis.sqlite"
    store = AnalysisSQLiteStore(path)
    store.upsert_prediction_record(
        {
            "prediction_id": "pred-read-1",
            "race_id": "202607051011",
            "theory_version": "v-read",
            "pre_race_snapshot": {"date": "2026-07-05", "course": "kokura", "race_no": 11},
            "prediction_json": {},
        }
    )
    with sqlite3.connect(path) as conn:
        conn.executemany(
            """
            insert into evaluations
            (evaluation_id, prediction_id, race_id, theory_version, total_bet, total_payout,
             return_rate, hit, gami, axis_in_top3, middle_hole_in_top3, firework_hit,
             max_odds_selected, evaluation_json, created_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "eval-read-1", "pred-read-1", "202607051011", "v-read", 200, 500,
                    2.5, 1, 0, 1, None, 0, 12.5, '{"note":"hit"}', "2026-07-05T16:00:00+00:00",
                ),
                (
                    "eval-read-2", "pred-read-2", "202607051011", "v-read", 300, 0,
                    0.0, 0, 0, 0, 1, None, None, "{}", "2026-07-05T15:00:00+00:00",
                ),
            ],
        )
        conn.executemany(
            """
            insert into evaluation_ticket_results
            (ticket_result_id, evaluation_id, ticket_id, bucket, bet_type, selection, amount, hit, payout)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("etr-read-1", "eval-read-1", "pt-read-1", "core", "wide", "2-10", 100, 1, 300),
                ("etr-read-2", "eval-read-1", "pt-read-2", "reserve", "win", "2", 100, 1, 200),
            ],
        )

    record = store.get_evaluation_record("eval-read-1")
    page = store.list_evaluation_records(
        race_id="202607051011",
        from_date=date(2026, 7, 5),
        to_date=date(2026, 7, 5),
        theory_version="v-read",
        limit=1,
        offset=0,
    )
    summary = store.summarize_evaluations(
        from_date=date(2026, 7, 5),
        to_date=date(2026, 7, 5),
        theory_version="v-read",
    )

    assert record.hit is True
    assert record.axis_in_top3 is True
    assert record.middle_hole_in_top3 is None
    assert record.evaluation == {"note": "hit"}
    assert record.ticket_results[0].hit is True
    assert page.total == 2
    assert len(page.items) == 1
    assert page.items[0].evaluation_id == "eval-read-1"
    assert summary.evaluation_count == 2
    assert summary.total_bet == 500
    assert summary.total_payout == 500
    assert summary.return_rate == 1.0
    assert summary.hit_rate == 0.5
    assert summary.axis_in_top3_rate == 0.5
    assert summary.middle_hole_in_top3_rate == 1.0
    assert summary.firework_hit_rate == 0.0
    assert summary.max_single_payout == 300
    assert summary.return_rate_without_max_payout == 0.4
    with pytest.raises(LookupError):
        store.get_evaluation_record("missing")
