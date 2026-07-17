from pathlib import Path

from jra_srb.config import load_parser_config
from jra_srb.extractors import parse_jra_table_odds, parse_race_card, parse_race_result


def test_parse_race_card_keeps_apprentice_marker_with_jockey_name():
    html = """
    <html>
      <body>
        <div class="race_header">
          <div class="race_name">Sample Race</div>
          <div class="type"><span class="course">芝 1200m</span></div>
          <div class="date_line"><span class="time"><strong>15:45</strong></span></div>
        </div>
        <table class="basic narrow-xy mt20">
          <tbody>
            <tr>
              <td class="num">8</td>
              <td class="horse">
                <p class="name"><a href="#">ヴォンヌヴォー</a></p>
                <p class="trainer"><a href="#">天間 昭一</a></p>
                <p class="odds"><strong>12.4</strong></p>
                <p class="pop_rank">5人気</p>
              </td>
              <td class="jockey">牝6/鹿 58.0 kg ▲ 黒岩</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """

    parsed = parse_race_card(html, load_parser_config("race_card"))

    assert parsed["race_name"] == "Sample Race"
    assert len(parsed["runners"]) == 1
    runner = parsed["runners"][0]
    assert runner.sex_age == "牝6/鹿"
    assert runner.weight_carried == "58.0 kg"
    assert runner.jockey == "▲黒岩"
    assert runner.trainer == "天間 昭一"
    assert parsed["data_status"]["runner_set"] == "complete"
    assert parsed["data_status"]["source_kind"] == "pre_race_card"


def test_parse_race_card_marks_explicit_withdrawal():
    html = """
    <div class="race_header">
      <div class="race_name">Sample Race</div>
    </div>
    <table class="basic narrow-xy mt20">
      <tbody>
        <tr>
          <td class="num">1</td>
          <td class="horse"><p class="name"><a>Active</a></p></td>
          <td class="jockey">牡3/鹿 56.0 kg 騎手A</td>
        </tr>
        <tr class="cancel">
          <td class="num">2</td>
          <td class="horse">
            <p class="name"><a>Withdrawn</a></p>
            <span>出走取消</span>
          </td>
          <td class="jockey">牡3/鹿 56.0 kg 騎手B</td>
        </tr>
      </tbody>
    </table>
    """

    parsed = parse_race_card(html, load_parser_config("race_card"))

    assert parsed["data_status"]["runner_set"] == "complete"
    assert parsed["runners"][0].status == "active"
    assert parsed["runners"][0].status_source is None
    assert parsed["runners"][1].status == "withdrawn"
    assert parsed["runners"][1].status_source == "explicit"


def test_parse_race_card_marks_incomplete_when_candidate_row_is_not_parsed():
    html = """
    <div class="race_header">
      <div class="race_name">Sample Race</div>
    </div>
    <table class="basic narrow-xy mt20">
      <tbody>
        <tr>
          <td class="num">1</td>
          <td class="horse"><p class="name"><a>Parsed</a></p></td>
        </tr>
        <tr>
          <td class="num">2</td>
          <td class="horse"></td>
        </tr>
      </tbody>
    </table>
    """

    parsed = parse_race_card(html, load_parser_config("race_card"))

    assert len(parsed["runners"]) == 1
    assert parsed["data_status"]["runner_set"] == "incomplete"
    assert "not fully parsed" in parsed["data_status"]["runner_set_reason"]


def test_parse_jra_race_card_extracts_horse_weight_from_fixture():
    fixture = Path("tests/fixtures/jradb_accessD_race_202603220611.html").read_text(
        encoding="shift_jis",
        errors="ignore",
    )

    parsed = parse_race_card(fixture, load_parser_config("race_card"))

    runners_by_no = {runner.horse_no: runner for runner in parsed["runners"]}
    assert runners_by_no["1"].horse_weight == "470"
    assert runners_by_no["1"].horse_weight_diff == "+4"
    assert runners_by_no["2"].horse_weight == "504"
    assert runners_by_no["2"].horse_weight_diff == "-4"
    assert runners_by_no["8"].horse_weight == "466"
    assert runners_by_no["8"].horse_weight_diff == "0"


def test_parse_race_result_supports_jra_result_page_fixture():
    fixture = Path("tests/fixtures/jradb_accessS_race_202603220611.html").read_text(
        encoding="shift_jis",
        errors="ignore",
    )

    parsed = parse_race_result(fixture, load_parser_config("race_result"))

    assert parsed["race_name"] is not None
    assert len(parsed["results"]) >= 10
    assert parsed["results"][0].rank == "1"
    assert parsed["results"][0].horse_no == "10"
    assert parsed["results"][0].jockey
    assert parsed["results"][0].time == "1:10.7"
    assert len(parsed["payouts"]) >= 8
    assert parsed["payouts"][0].bet_type == "単勝"
    assert parsed["payouts"][0].combination == "10"


def test_parse_jra_table_odds_supports_current_quinella_markup():
    html = """
    <div id="odds_list">
      <table class="basic narrow-xy umaren">
        <caption>2</caption>
        <tbody><tr><th scope="row">14</th><td><strong class="red">5.8</strong></td></tr></tbody>
      </table>
    </div>
    """

    entries = parse_jra_table_odds(html, bet_type="quinella", leg_count=2)

    assert len(entries) == 1
    assert entries[0].combination == ["2", "14"]
    assert entries[0].odds == "5.8"


def test_parse_jra_table_odds_supports_current_wide_markup():
    html = """
    <div id="odds_list">
      <table class="basic narrow-xy wide">
        <caption>2</caption>
        <tbody>
          <tr>
            <th scope="row">14</th>
            <td class="odds"><span class="inner"><span class="min">2.8</span><span class="cap">-</span><span class="max">3.2</span></span></td>
          </tr>
        </tbody>
      </table>
    </div>
    """

    entries = parse_jra_table_odds(html, bet_type="wide", leg_count=2)

    assert len(entries) == 1
    assert entries[0].combination == ["2", "14"]
    assert entries[0].odds is None
    assert entries[0].odds_min == "2.8"
    assert entries[0].odds_max == "3.2"


def test_parse_jra_table_odds_supports_current_trio_markup():
    html = """
    <div id="odds_list">
      <table class="basic narrow-xy fuku3">
        <caption>2-8</caption>
        <tbody><tr><th scope="row">14</th><td><strong class="red">31.8</strong></td></tr></tbody>
      </table>
    </div>
    """

    entries = parse_jra_table_odds(html, bet_type="trio", leg_count=3)

    assert len(entries) == 1
    assert entries[0].combination == ["2", "8", "14"]
    assert entries[0].odds == "31.8"


def test_parse_jra_table_odds_supports_current_exacta_markup():
    html = """
    <div id="odds_list">
      <table class="basic narrow-xy umatan">
        <caption>14</caption>
        <tbody><tr><th scope="row">2</th><td><strong class="red">12.4</strong></td></tr></tbody>
      </table>
    </div>
    """

    entries = parse_jra_table_odds(html, bet_type="exacta", leg_count=2)

    assert len(entries) == 1
    assert entries[0].combination == ["14", "2"]
    assert entries[0].odds == "12.4"
