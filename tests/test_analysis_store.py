from datetime import UTC, date, datetime
import sqlite3

import pytest

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.models import (
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


def test_analysis_store_rejects_invalid_count_table(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")

    with pytest.raises(ValueError):
        store.count_rows("races; drop table races")
