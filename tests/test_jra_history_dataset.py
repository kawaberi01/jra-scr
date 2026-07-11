from jra_srb.jra_history_dataset import COURSE_CODES, FEATURE_NAMES, build_history_dataset_from_rows


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
