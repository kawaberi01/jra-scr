from datetime import date
import sqlite3
from types import SimpleNamespace

from jra_srb.jra_history_dataset import (
    COURSE_CODES, FEATURE_NAMES, build_history_dataset, build_history_dataset_from_rows,
    build_live_feature_records,
)


def _row(race_id, race_date, horse_no, horse_name, rank, jockey, trainer):
    return {
        "race_id": race_id, "race_date": race_date, "race_name": "3歳未勝利",
        "surface": "ダート", "distance": "1,800", "horse_no": str(horse_no),
        "frame_no": str((horse_no + 1) // 2), "horse_name": horse_name,
        "sex_age": "牡3", "weight_carried": "57.0", "jockey": jockey,
        "trainer": trainer, "rank": rank,
    }


def test_history_dataset_normalizes_course_without_changing_input_and_avoids_same_race_leakage():
    rows = [
        _row("202401060601", "2024-01-06", 1, "ホースA", 1, "騎手A", "厩舎A"),
        _row("202401060601", "2024-01-06", 2, "ホースB", 2, "騎手B", "厩舎B"),
        _row("202401130601", "2024-01-13", 1, "ホースA", 2, "騎手A", "厩舎A"),
        _row("202401130601", "2024-01-13", 2, "ホースB", 1, "騎手B", "厩舎B"),
    ]
    records, metadata = build_history_dataset_from_rows(rows)
    starts = FEATURE_NAMES.index("horse_log_starts")
    assert records[0]["course"] == "nakayama"
    assert records[0]["features"][FEATURE_NAMES.index("course_nakayama")] == 1.0
    assert records[0]["features"][starts] == 0.0
    assert records[1]["features"][starts] == 0.0
    assert records[2]["features"][starts] > 0.0
    assert rows[0]["surface"] == "ダート"
    assert metadata["races"] == 2
    assert metadata["source_db_mutated"] is False


def test_feature_names_and_course_codes_are_stable():
    assert len(FEATURE_NAMES) == 43
    assert COURSE_CODES["01"] == "sapporo"
    assert COURSE_CODES["10"] == "kokura"


def test_live_features_use_only_rows_before_target_date(tmp_path):
    db = tmp_path / "history.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            create table races (race_id text primary key, race_date text, race_name text, surface text, distance text, source text);
            create table runners (race_id text, horse_no text, frame_no text, horse_name text, sex_age text, weight_carried text, jockey text, trainer text);
            create table result_entries (race_id text, horse_no text, rank integer);
            create table payouts (race_id text);
            """
        )
        conn.execute("insert into races values (?,?,?,?,?,?)", ("202401060601", "2024-01-06", "3歳未勝利", "ダート", "1,800", "https://www.jra.go.jp/JRADB/accessS.html"))
        conn.executemany("insert into runners values (?,?,?,?,?,?,?,?)", [
            ("202401060601", "1", "1", "ホースA", "牡3", "57.0", "騎手A", "厩舎A"),
            ("202401060601", "2", "1", "ホースB", "牡3", "57.0", "騎手B", "厩舎B"),
        ])
        conn.executemany("insert into result_entries values (?,?,?)", [("202401060601", "1", 1), ("202401060601", "2", 2)])
        conn.execute("insert into payouts values (?)", ("202401060601",))
    card = SimpleNamespace(
        race_id="202401130601", race_name="3歳未勝利", surface="ダート", distance="1,800",
        runners=[SimpleNamespace(horse_no="1", frame_no="1", horse_name="ホースA", sex_age="牡3", weight_carried="57.0", jockey="騎手A", trainer="厩舎A")],
    )
    records = build_live_feature_records(db, target_date=date(2024, 1, 13), course="nakayama", card=card)
    assert records[0]["history_starts"] == 1
    assert records[0]["history_as_of"] == "2024-01-13T00:00:00"


def test_history_dataset_can_be_cut_off_before_live_target(tmp_path):
    db = tmp_path / "history.sqlite"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
            create table races (race_id text primary key, race_date text, race_name text, surface text, distance text, source text);
            create table runners (race_id text, horse_no text, frame_no text, horse_name text, sex_age text, weight_carried text, jockey text, trainer text);
            create table result_entries (race_id text, horse_no text, rank integer);
            create table payouts (race_id text);
        """)
        for race_id, race_date in (("202401060601", "2024-01-06"), ("202401130601", "2024-01-13")):
            conn.execute("insert into races values (?,?,?,?,?,?)", (race_id, race_date, "3歳未勝利", "ダート", "1,800", "https://www.jra.go.jp/JRADB/accessS.html"))
            conn.executemany("insert into runners values (?,?,?,?,?,?,?,?)", [(race_id, "1", "1", "A", "牡3", "57.0", "J", "T"), (race_id, "2", "2", "B", "牡3", "57.0", "K", "U")])
            conn.executemany("insert into result_entries values (?,?,?)", [(race_id, "1", 1), (race_id, "2", 2)])
            conn.execute("insert into payouts values (?)", (race_id,))
    records, metadata = build_history_dataset(db, through_date=date(2024, 1, 6))
    assert {record["race_id"] for record in records} == {"202401060601"}
    assert metadata["date_max"] == "2024-01-06"
