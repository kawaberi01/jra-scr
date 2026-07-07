from datetime import date

from jra_srb.nankankeiba_pattern_extractors import (
    build_pattern_race_id,
    build_pattern_url_path,
    parse_pattern_category_page,
    parse_pattern_rate,
)


RACE_ID = "202607062104010101"


def _fixture(category: str) -> str:
    return open(f"tests/fixtures/nankankeiba_{category}_{RACE_ID}.html", "rb").read().decode("cp932")


def test_build_pattern_race_id_for_kawasaki_lifetime():
    assert build_pattern_race_id(date(2026, 7, 6), "kawasaki", 4, 1, 1, "01") == RACE_ID
    assert build_pattern_race_id(date(2026, 7, 6), "川崎", 4, 1, 1, "lifetime") == RACE_ID


def test_build_pattern_url_path_for_all_categories():
    assert build_pattern_url_path("pattern_kis", RACE_ID) == f"/pattern_kis/{RACE_ID}.do"
    assert build_pattern_url_path("pattern_uma", RACE_ID) == f"/pattern_uma/{RACE_ID}.do"
    assert build_pattern_url_path("pattern_cho", RACE_ID) == f"/pattern_cho/{RACE_ID}.do"
    assert build_pattern_url_path("pattern_kis_cho", RACE_ID) == f"/pattern_kis_cho/{RACE_ID}.do"


def test_parse_pattern_rate_returns_numeric_values_and_allows_missing():
    parsed = parse_pattern_rate("14.5% (256/1770)")

    assert parsed.rate == 14.5
    assert parsed.wins == 256
    assert parsed.starts == 1770
    assert parse_pattern_rate("").rate is None


def test_parse_pattern_category_page_extracts_seven_runners():
    entries = parse_pattern_category_page(_fixture("pattern_kis"), RACE_ID, "pattern_kis")

    assert len(entries) == 7
    assert entries[4].horse_no == "5"
    assert entries[4].horse_name == "ヘヴンリーゴール"
    assert entries[4].jockey == "野畑凌"
    assert entries[4].trainer == "吉橋淳"
    assert entries[4].rates["kawasaki"].rate == 14.5
    assert entries[4].rates["kawasaki"].wins == 256
    assert entries[4].rates["kawasaki"].starts == 1770


def test_parse_all_four_categories_have_matching_horse_numbers():
    category_entries = {
        category: parse_pattern_category_page(_fixture(category), RACE_ID, category)
        for category in ("pattern_kis", "pattern_uma", "pattern_cho", "pattern_kis_cho")
    }

    horse_numbers = [{entry.horse_no for entry in entries} for entries in category_entries.values()]

    assert all(len(entries) == 7 for entries in category_entries.values())
    assert horse_numbers == [horse_numbers[0]] * 4


def test_parse_pattern_uma_uses_category_specific_column_mapping():
    entries = parse_pattern_category_page(_fixture("pattern_uma"), RACE_ID, "pattern_uma")

    assert len(entries) == 7
    assert all(entry.rates["kawasaki"].rate is not None for entry in entries)
    assert all(entry.rates["medium"].rate is not None for entry in entries)

    heavenly_goal = entries[4]
    assert heavenly_goal.horse_name == "ヘヴンリーゴール"
    assert heavenly_goal.rates["kawasaki"].rate == 20.0
    assert heavenly_goal.rates["kawasaki"].wins == 1
    assert heavenly_goal.rates["kawasaki"].starts == 5
    assert heavenly_goal.rates["short"].rate == 50.0
    assert heavenly_goal.rates["short"].wins == 1
    assert heavenly_goal.rates["short"].starts == 2
    assert heavenly_goal.rates["medium"].rate == 16.7
    assert heavenly_goal.rates["medium"].wins == 2
    assert heavenly_goal.rates["medium"].starts == 12
    assert heavenly_goal.rates["popularity_1"].rate == 66.7
    assert heavenly_goal.rates["popularity_2"].rate == 0.0
    assert heavenly_goal.rates["popularity_3"].rate is None
    assert heavenly_goal.rates["popularity_4_or_more"].rate == 7.1
    assert heavenly_goal.jockey_riding_rate is not None
    assert heavenly_goal.jockey_riding_rate.rate == 33.3
    assert heavenly_goal.track_condition_rates["good"].rate == 33.3
    assert heavenly_goal.season_rates["apr_to_jun"].rate == 0.0
    assert heavenly_goal.frame_group_rates["frame_5_6"].rate == 22.2
