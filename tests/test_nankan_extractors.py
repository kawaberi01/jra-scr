from pathlib import Path
from datetime import date

from jra_srb.nankan_extractors import (
    parse_nankan_meeting,
    parse_nankan_best_time,
    parse_nankan_closing_speed,
    parse_nankan_horse_recent_races,
    parse_nankan_leading_jockeys,
    parse_nankan_meeting_trend,
    parse_nankan_odds,
    parse_nankan_race_card,
    parse_nankan_race_result,
)


def _read(name: str) -> str:
    return Path("tests/fixtures", name).read_text(encoding="utf-8")


def test_parse_nankan_meeting_extracts_races():
    parsed = parse_nankan_meeting(_read("nankan_program_20260704190405.html"), date(2026, 7, 4), "funabashi")

    assert parsed["course"] == "funabashi"
    assert len(parsed["races"]) == 2
    assert parsed["races"][0].race_no == 1
    assert parsed["races"][0].race_id == "2026070419040501"
    assert parsed["races"][0].race_name == "３歳(九) 未受賞"
    assert parsed["races"][0].start_time == "14:35"


def test_parse_nankan_race_card_extracts_runner():
    parsed = parse_nankan_race_card(_read("nankan_card_2026070419040501.html"))

    assert parsed["course"] == "funabashi"
    assert parsed["surface"] == "dirt"
    assert parsed["surface_label"] == "ダ"
    assert parsed["distance"] == "1200"
    assert parsed["start_time"] == "14:35"
    assert parsed["runners"][0].horse_name == "トーセンレクサム"
    assert parsed["runners"][0].horse_weight == "503"
    assert parsed["runners"][0].horse_weight_diff == "+24"


def test_parse_nankan_race_card_keeps_runner_without_frame_no():
    parsed = parse_nankan_race_card(_read("nankan_card_2026070621040111.html"))

    assert parsed["race_name"] == "アクルックス賞"
    assert parsed["surface"] == "dirt"
    assert parsed["surface_label"] == "ダ"
    assert parsed["distance"] == "2000"
    assert parsed["start_time"] == "20:15"
    assert [runner.horse_no for runner in parsed["runners"]] == [str(number) for number in range(1, 10)]
    assert parsed["runners"][-1].frame_no is None
    assert parsed["runners"][-1].horse_no == "9"
    assert parsed["runners"][-1].horse_name == "オウケンデューク 20.5.6(中同名)"
    assert parsed["runners"][-1].jockey == "野畑凌 (川崎)"


def test_parse_nankan_meeting_extracts_conditions():
    parsed = parse_nankan_meeting(_read("nankan_program_20260706210401.html"), date(2026, 7, 6), "kawasaki")

    assert parsed["weather"] == "rainy"
    assert parsed["weather_label"] == "雨"
    assert parsed["track_condition"] == "heavy"
    assert parsed["track_condition_label"] == "重"
    assert parsed["surface"] == "dirt"
    assert parsed["surface_label"] == "ダ"
    assert parsed["races"][-1].race_no == 11
    assert parsed["races"][-1].surface == "dirt"
    assert parsed["races"][-1].distance == "2000"
    assert parsed["races"][-1].weather == "rainy"
    assert parsed["races"][-1].track_condition == "heavy"


def test_parse_nankan_meeting_trend_extracts_structured_summary():
    parsed = parse_nankan_meeting_trend(_read("nankan_trend_2026210401_20260706.html"))
    summary = parsed["summary"]

    assert parsed["updated_at"].isoformat() == "2026-07-06T21:24:00+09:00"
    assert parsed["race_count_completed"] == 12
    assert summary.frame[0].frame_no == "6"
    assert summary.frame[0].top3_count == 8
    assert summary.running_style.front_group_top3_count == 27
    assert summary.running_style.back_group_top3_count == 9
    assert summary.jockey[0].name == "笹川翼"
    assert summary.jockey[0].affiliation == "大井"
    assert summary.trainer[0].name == "高月賢一"
    assert summary.trainer[0].affiliation == "川崎"
    assert summary.sire[-1].name == "ロードカナロア"
    assert summary.broodmare_sire[0].top3_count == 4
    assert summary.payout.trifecta_max_payout == 109080
    assert summary.payout.trifecta_max_payout_race_no == 7


def test_parse_nankan_best_time_extracts_rows():
    parsed = parse_nankan_best_time(_read("nankan_best_2026070621040101000000.html"), "kawasaki", 1400)
    runner = parsed["runners"][0]

    assert runner.horse_no == "5"
    assert runner.horse_name == "ヘヴンリーゴール"
    assert runner.best_time == "1:31.8"
    assert runner.best_time_rank == 1
    assert runner.best_time_source_course == "kawasaki"
    assert runner.best_time_source_distance == 1400
    assert runner.same_course_flag is True
    assert runner.same_distance_flag is True
    assert runner.track_condition == "good"
    assert runner.horse_profile_id == "2022101194"


def test_parse_nankan_closing_speed_extracts_rows():
    parsed = parse_nankan_closing_speed(_read("nankan_best_2026070621040101221400.html"), "kawasaki", 1400)
    runner = parsed["runners"][0]

    assert runner.horse_no == "5"
    assert runner.best_closing_time == "39.5"
    assert runner.best_closing_rank == 1
    assert runner.same_course_flag is True
    assert runner.same_distance_flag is True
    assert runner.track_condition == "good"


def test_parse_nankan_horse_recent_races_extracts_corner_positions():
    races = parse_nankan_horse_recent_races(_read("nankan_horse_2022101194.html"))

    assert len(races) == 2
    assert races[0].source_date.isoformat() == "2026-06-18"
    assert races[0].course == "kawasaki"
    assert races[0].race_no == 6
    assert races[0].corner_positions == [7, 7, 4]
    assert races[0].field_size == 12
    assert races[0].distance == 1400
    assert races[0].track_condition == "heavy"
    assert races[0].finish_rank == 5


def test_parse_nankan_leading_jockeys_extracts_header_based_table():
    parsed = parse_nankan_leading_jockeys(_read("nankan_leading_jockeys_211400010004031.html"))

    assert len(parsed) == 2
    assert parsed[0].rank == 1
    assert parsed[0].jockey_code == "12345"
    assert parsed[0].jockey_name == "野畑凌"
    assert parsed[0].rides == 120
    assert parsed[0].wins == 24
    assert parsed[0].seconds == 18
    assert parsed[0].thirds == 11
    assert parsed[0].win_rate == 20.0
    assert parsed[0].quinella_rate == 35.0
    assert parsed[0].trio_rate == 44.2


def test_parse_nankan_leading_jockeys_returns_empty_without_table():
    parsed = parse_nankan_leading_jockeys("<html><body><p>no data</p></body></html>")

    assert parsed == []


def test_parse_nankan_win_place_odds():
    win = parse_nankan_odds(_read("nankan_odds_202607041904050101.html"), "win")
    place = parse_nankan_odds(_read("nankan_odds_202607041904050101.html"), "place")

    assert win["win"][0].combination == ["1"]
    assert win["win"][0].odds == "18.3"
    assert place["place"][0].odds_min == "2.1"
    assert place["place"][0].odds_max == "4.7"


def test_parse_nankan_win_odds_keeps_rowspan_rows_and_null_odds():
    win = parse_nankan_odds(_read("nankan_odds_202607062104010301.html"), "win")

    assert len(win["win"]) == 12
    assert [entry.combination[0] for entry in win["win"]] == [str(number) for number in range(1, 13)]
    assert win["win"][5].odds == "6.6"
    assert win["win"][7].odds == "8.8"
    assert win["win"][9].odds == "10.1"
    assert win["win"][11].odds is None


def test_parse_nankan_pair_odds_and_ranges():
    quinella = parse_nankan_odds(_read("nankan_odds_202607041904050104.html"), "quinella")
    wide = parse_nankan_odds(_read("nankan_odds_202607041904050104.html"), "wide")

    assert quinella["quinella"][0].combination == ["1", "2"]
    assert quinella["quinella"][0].odds == "149.8"
    assert wide["wide"][0].odds_min == "33.3"
    assert wide["wide"][0].odds_max == "36.4"


def test_parse_nankan_exacta_trio_trifecta_skip_invalid_marks():
    exacta = parse_nankan_odds(_read("nankan_odds_202607041904050103.html"), "exacta")
    trio = parse_nankan_odds(_read("nankan_odds_202607041904050109.html"), "trio")
    trifecta = parse_nankan_odds(_read("nankan_odds_202607041904050108.html"), "trifecta")

    assert exacta["exacta"][0].combination == ["2", "1"]
    assert exacta["exacta"][0].odds == "602.8"
    assert all(entry.odds != "−" for entry in exacta["exacta"])
    assert trio["trio"][0].combination == ["1", "2", "3"]
    assert trifecta["trifecta"][0].combination == ["1", "3", "2"]


def test_parse_nankan_race_result_extracts_results_and_payouts():
    parsed = parse_nankan_race_result(_read("nankan_result_2026070419040501.html"))

    assert parsed["race_name"] == "3歳(九) 未受賞"
    assert parsed["results"][0].rank == "1"
    assert parsed["results"][0].horse_no == "6"
    assert parsed["results"][0].horse_name == "イデスホープ"
    assert parsed["results"][0].jockey == "山中悠希"
    assert parsed["results"][0].time == "1:16.2"
    assert [entry.bet_type for entry in parsed["payouts"]] == [
        "win",
        "place",
        "place",
        "quinella",
        "wide",
        "exacta",
        "trio",
        "trifecta",
    ]
    assert parsed["payouts"][0].combination == "6"
    assert parsed["payouts"][0].payout == "130"
    assert parsed["payouts"][-1].combination == "6-8-3"
    assert parsed["payouts"][-1].payout == "2400"


def test_parse_nankan_race_result_extracts_official_grouped_payouts():
    parsed = parse_nankan_race_result(_read("nankan_result_2026070621040101.html"))

    assert parsed["race_name"] == "Ｃ３(一)(二)"
    assert parsed["results"][0].rank == "1"
    assert parsed["results"][0].horse_no == "5"
    assert parsed["results"][0].horse_name == "ヘヴンリーゴール"
    assert parsed["results"][0].jockey == "野畑凌"
    assert parsed["results"][0].time == "1:33.7"
    assert [entry.bet_type for entry in parsed["payouts"]] == [
        "win",
        "place",
        "place",
        "quinella",
        "exacta",
        "wide",
        "wide",
        "trio",
        "trifecta",
    ]
    assert parsed["payouts"][3].combination == "3-5"
    assert parsed["payouts"][3].payout == "4990"
    assert parsed["payouts"][-1].combination == "5-3-2"
    assert parsed["payouts"][-1].payout == "31960"


def test_parse_nankan_race_result_requires_result_table():
    try:
        parse_nankan_race_result("<html><body><p>no result</p></body></html>")
    except LookupError as exc:
        assert "result table" in str(exc)
    else:
        raise AssertionError("LookupError was not raised")
