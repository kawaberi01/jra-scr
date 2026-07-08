from datetime import UTC, date, datetime
import sqlite3

import pytest

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.models import (
    BetRecordCreateRequest,
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

    assert snapshot["race"]["race_id"] == "202603220611"
    assert snapshot["runners"][0]["horse_name"] == "Dragon Wells"
    assert snapshot["runners"][0]["card_odds"] == 12.4
    assert snapshot["odds"][0]["entries"][0]["odds"] == 16.1
    assert "results" not in snapshot
    assert "payouts" not in snapshot
    assert store.count_rows("result_entries") == 1
    assert store.count_rows("payouts") == 1
    assert store.has_card("202603220611") is True
    assert store.has_result("202603220611") is True
    assert store.has_odds_snapshot("202603220611", "wide") is True


def test_analysis_store_upserts_card_and_odds_without_duplicates(tmp_path):
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
    assert store.count_rows("odds_snapshots") == 1
    assert store.count_rows("odds_entries") == 1


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
