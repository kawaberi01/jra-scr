from pathlib import Path

from jra_srb.netkeiba_extractors import parse_netkeiba_odds_payload, parse_netkeiba_race_result


def test_parse_netkeiba_race_result_fixture_extracts_result_details():
    html = Path("tests/fixtures/netkeiba_race_result_202605021211.html").read_bytes().decode("utf-8")

    parsed = parse_netkeiba_race_result(html)

    assert parsed["race_name"] == "日本ダービー"
    assert parsed["date"] == "2026-05-31"
    assert parsed["course"] == "東京"
    assert parsed["race_no"] == "11"
    assert parsed["surface"] == "芝"
    assert parsed["distance"] == "2400"
    assert parsed["direction"] == "左 C"
    assert parsed["weather"] == "晴"
    assert parsed["track_condition"] == "良"
    assert len(parsed["results"]) == 18

    winner = parsed["results"][0]
    assert winner.rank == "1"
    assert winner.frame_no == "8"
    assert winner.horse_no == "17"
    assert winner.horse_name == "ロブチェン"
    assert winner.sex_age == "牡3"
    assert winner.weight_carried == "57.0"
    assert winner.jockey == "松山"
    assert winner.trainer == "栗東・杉山晴"
    assert winner.horse_weight == "522"
    assert winner.horse_weight_diff == "+2"
    assert winner.finish_time == "2:22.7"
    assert winner.final_3f == "33.2"
    assert winner.win_odds == "2.7"
    assert winner.popularity == "1"

    assert any(
        payout.bet_type == "trifecta"
        and payout.combination == "17-13-5"
        and payout.payout == "47,050"
        and payout.popularity == "140"
        for payout in parsed["payouts"]
    )


def test_parse_netkeiba_odds_payload_fixture_extracts_supported_bet_types():
    content = Path("tests/fixtures/netkeiba_odds_api_202605021211.json").read_text(encoding="utf-8")

    odds = parse_netkeiba_odds_payload(content)

    assert {"win", "place", "quinella", "wide", "exacta", "trio", "trifecta"}.issubset(odds)
    assert odds["win"][0].combination == ["17"]
    assert odds["win"][0].odds == "2.7"
    assert odds["win"][0].popularity == "1"

    wide = next(entry for entry in odds["wide"] if entry.combination == ["13", "17"])
    assert wide.odds_min == "5.1"
    assert wide.odds_max == "5.6"
    assert wide.popularity == "3"

    trifecta = next(entry for entry in odds["trifecta"] if entry.combination == ["17", "13", "5"])
    assert trifecta.odds == "470.5"
