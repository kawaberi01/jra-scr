from datetime import date
import sqlite3

from jra_srb.jra_history_dataset import FEATURE_NAMES
from jra_srb.jra_recent_form_dataset import (
    RECENT_FORM_FEATURE_NAMES, append_recent_form_features,
    append_recent_form_live_features,
)


def _record(race_id: str, race_date: str, rank: int) -> dict:
    return {
        "race_id": race_id, "race_date": race_date, "horse_no": "1", "horse_name": "A",
        "actual_rank": rank, "features": [0.5] * len(FEATURE_NAMES),
    }


def test_recent_form_uses_only_prior_races() -> None:
    enriched = append_recent_form_features([
        _record("202401060601", "2024-01-06", 1),
        _record("202401130601", "2024-01-13", 2),
    ])
    offset = len(FEATURE_NAMES)
    assert enriched[0]["features"][offset + RECENT_FORM_FEATURE_NAMES.index("form_history_count_scaled")] == 0.0
    assert enriched[1]["features"][offset + RECENT_FORM_FEATURE_NAMES.index("form_last_finish_strength")] == 1.0


def test_live_recent_form_excludes_target_date(tmp_path) -> None:
    db = tmp_path / "history.sqlite"
    with sqlite3.connect(db) as connection:
        connection.executescript("""
            create table races (race_id text, race_date text, source text);
            create table runners (race_id text, horse_no text, horse_name text);
            create table result_entries (race_id text, horse_no text, rank integer);
            create table payouts (race_id text);
        """)
        for race_id, race_date, rank in (
            ("202401060601", "2024-01-06", 1),
            ("202401130601", "2024-01-13", 9),
        ):
            connection.execute("insert into races values (?,?,?)", (race_id, race_date, "https://www.jra.go.jp/"))
            connection.execute("insert into runners values (?,?,?)", (race_id, "1", "A"))
            connection.execute("insert into result_entries values (?,?,?)", (race_id, "1", rank))
            connection.execute("insert into payouts values (?)", (race_id,))
    record = _record("202401130601", "2024-01-13", 0)
    enriched = append_recent_form_live_features([record], db, target_date=date(2024, 1, 13))
    offset = len(FEATURE_NAMES)
    assert enriched[0]["features"][offset + RECENT_FORM_FEATURE_NAMES.index("form_last_finish_strength")] == 1.0


def test_live_recent_form_skips_missing_finish_rank(tmp_path) -> None:
    db = tmp_path / "history.sqlite"
    with sqlite3.connect(db) as connection:
        connection.executescript("""
            create table races (race_id text, race_date text, source text);
            create table runners (race_id text, horse_no text, horse_name text);
            create table result_entries (race_id text, horse_no text, rank integer);
            create table payouts (race_id text);
        """)
        for race_id, race_date, rank in (
            ("202401060601", "2024-01-06", 1),
            ("202401070601", "2024-01-07", None),
        ):
            connection.execute("insert into races values (?,?,?)", (race_id, race_date, "https://www.jra.go.jp/"))
            connection.execute("insert into runners values (?,?,?)", (race_id, "1", "A"))
            connection.execute("insert into result_entries values (?,?,?)", (race_id, "1", rank))
            connection.execute("insert into payouts values (?)", (race_id,))
    record = _record("202401130601", "2024-01-13", 0)
    enriched = append_recent_form_live_features([record], db, target_date=date(2024, 1, 13))
    offset = len(FEATURE_NAMES)
    assert enriched[0]["features"][offset + RECENT_FORM_FEATURE_NAMES.index("form_history_count_scaled")] == 0.2
    assert enriched[0]["features"][offset + RECENT_FORM_FEATURE_NAMES.index("form_last_finish_strength")] == 1.0
