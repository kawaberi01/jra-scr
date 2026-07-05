from pathlib import Path

from jra_srb.nar_netkeiba_extractors import (
    parse_nar_calendar,
    parse_nar_meeting,
    parse_nar_odds,
    parse_nar_race_card,
    parse_nar_race_result,
)


def _read(name: str) -> str:
    return Path("tests/fixtures", name).read_text(encoding="utf-8", errors="ignore")


def test_parse_nar_calendar_extracts_kawasaki_dates():
    entries = parse_nar_calendar(_read("nar_calendar_202606_jyo45.html"))

    assert len(entries) == 5
    assert entries[0].date.isoformat() == "2026-06-15"
    assert entries[0].course == "川崎"
    assert entries[0].course_key == "kawasaki"
    assert entries[0].kaisai_id == "2026450615"


def test_parse_nar_meeting_extracts_active_venue_races():
    parsed = parse_nar_meeting(_read("nar_race_list_sub_2026450615.html"), "2026450615")

    assert parsed["course"] == "川崎"
    assert len(parsed["races"]) == 12
    assert parsed["races"][0].race_id == "202645061501"
    assert parsed["races"][0].race_name == "ラファール賞(3歳)"
    assert parsed["races"][0].start_time == "15:00"


def test_parse_nar_race_card_extracts_runner_weight_and_odds():
    parsed = parse_nar_race_card(_read("nar_race_card_202645061501.html"))

    assert parsed["race_name"] == "ラファール賞(3歳)"
    assert parsed["course"] == "川崎"
    assert parsed["surface"] == "ダート"
    assert parsed["distance"] == "900"
    assert parsed["start_time"] == "15:00"
    assert parsed["runners"][0].horse_name == "イアソン"
    assert parsed["runners"][0].horse_weight == "440"
    assert parsed["runners"][0].horse_weight_diff == "-7"
    assert parsed["runners"][0].odds == "129.3"
    assert parsed["runners"][0].popularity == "8"


def test_parse_nar_race_result_extracts_entries_payouts_and_corner_order():
    parsed = parse_nar_race_result(_read("nar_race_result_202645061501.html"))

    assert parsed["date"] == "2026-06-15"
    assert parsed["course"] == "川崎"
    assert parsed["race_no"] == "1"
    assert parsed["results"][0].horse_name == "グランドマーメイド"
    assert parsed["results"][0].horse_weight == "457"
    assert parsed["results"][0].horse_weight_diff == "-2"
    assert parsed["results"][0].win_odds == "3.3"
    assert any(payout.bet_type == "trifecta" and payout.combination == "2-9-4" for payout in parsed["payouts"])
    assert parsed["corner_passages"][0].startswith("2")


def test_parse_nar_odds_supports_single_pair_and_trio_pages():
    wide = parse_nar_odds(_read("nar_odds_b5_202645061501.html"))
    trio = parse_nar_odds(_read("nar_odds_b7_202645061501.html"))
    exacta = parse_nar_odds(_read("nar_odds_b6_202645061501.html"))

    assert wide["wide"][12].combination == ["2", "4"]
    assert wide["wide"][12].odds_min == "1.6"
    assert wide["wide"][12].odds_max == "2.0"
    assert trio["trio"][1].combination == ["1", "2", "4"]
    assert trio["trio"][1].odds == "69.9"
    assert exacta["exacta"][13].combination == ["2", "4"]
    assert exacta["exacta"][13].odds == "7.3"
