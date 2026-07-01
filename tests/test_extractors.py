from pathlib import Path

from jra_srb.config import load_parser_config
from jra_srb.extractors import parse_race_card, parse_race_result


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
