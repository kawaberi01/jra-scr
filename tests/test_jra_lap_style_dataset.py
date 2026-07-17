from __future__ import annotations

import math
import sqlite3

from jra_srb.jra_lap_style_dataset import append_lap_style_features


def test_style_features_use_only_prior_dates(tmp_path) -> None:
    db_path = tmp_path / "analysis.sqlite"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            create table netkeiba_race_results (netkeiba_race_id text primary key, race_laps_json text);
            create table netkeiba_result_entries (netkeiba_race_id text, jra_race_id text, horse_no text, corner_order text, final_3f real);
            create table netkeiba_race_mappings (netkeiba_race_id text, jra_race_id text, mapping_status text);
            """
        )
        connection.execute("insert into netkeiba_race_results values ('n1', '[12.0,12.0,13.0,13.0]')")
        connection.execute("insert into netkeiba_race_mappings values ('n1', 'r1', 'mapped')")
        connection.executemany(
            "insert into netkeiba_result_entries values ('n1','r1',?,?,?)",
            [("1", "1-1-1-1", 34.0), ("2", "2-2-2-2", 35.0)],
        )
    records = [
        {"race_id": "r1", "race_date": "2024-01-01", "horse_no": "1", "horse_name": "A", "course": "Tokyo", "surface": "turf", "distance": 1600, "features": [0.0]},
        {"race_id": "r1", "race_date": "2024-01-01", "horse_no": "2", "horse_name": "B", "course": "Tokyo", "surface": "turf", "distance": 1600, "features": [0.0]},
        {"race_id": "r2", "race_date": "2024-01-02", "horse_no": "1", "horse_name": "A", "course": "Tokyo", "surface": "turf", "distance": 1600, "features": [0.0]},
    ]

    enriched, metadata = append_lap_style_features(records, db_path)

    assert metadata["runner_extras"] == 2
    assert metadata["race_lap_races"] == 1
    assert enriched[0]["features"][1] == 0.0
    assert enriched[2]["features"][1] == math.log1p(1)
    assert enriched[2]["features"][4] == 1.0
    assert enriched[2]["features"][12] == math.log1p(1)
    assert enriched[2]["features"][13] == 1.0
