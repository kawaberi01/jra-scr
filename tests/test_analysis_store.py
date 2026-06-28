from datetime import UTC, date, datetime
import sqlite3

import pytest

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.models import (
    MeetingRace,
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
