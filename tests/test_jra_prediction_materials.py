from datetime import date
from pathlib import Path

from jra_srb.jra_prediction_materials import build_source_keys
from jra_srb.jra_public_analysis_extractors import (
    parse_keibalab_umabashira,
    parse_netkeiba_data_top,
    parse_umanity_race,
)


def test_build_source_keys_for_fukushima_today():
    keys = build_source_keys(date(2026, 7, 11), "fukushima", 5, 2, 5)
    assert keys.jra_internal_race_id == "202607110305"
    assert keys.netkeiba_race_id == "202603020505"
    assert keys.keibalab_race_code == "202607110305"
    assert keys.umanity_race_code == "2026071103020505"


def test_public_extractors_keep_only_visible_fields():
    netkeiba = parse_netkeiba_data_top(
        '<div class="RaceDataPickupList Not_Premium"><table class="PickupRaceDataTable01">'
        '<th class="PickupHorseTableTitle">好走騎手</th><td><span class="Txt">戸崎圭太</span></td></table></div>',
        "https://example.test/netkeiba",
    )
    assert netkeiba.course_analysis["好走騎手"] == ["戸崎圭太"]

    keibalab = parse_keibalab_umabashira(
        '<table class="megamoriTable"><tr class="umaban"><td><i>1</i></td></tr>'
        '<tr><td><a class="bamei">テストホース</a></td></tr>'
        '<tr><th>Ω指数</th><td>88.5</td></tr></table>',
        "https://example.test/keibalab",
    )
    assert keibalab.runners[0].horse_name == "テストホース"
    assert keibalab.runners[0].omega_index == 88.5

    umanity = parse_umanity_race(
        '<a onclick="open_register_vip()">前走情報</a>', "https://example.test/umanity"
    )
    assert umanity.status == "unavailable"
    assert umanity.locked_fields == ["前走情報"]


def test_keibalab_recent_races_keep_blank_initial_runner_column():
    html = Path("tests/fixtures/keibalab_umabashira_initial_runner.html").read_text(encoding="utf-8")

    keibalab = parse_keibalab_umabashira(html, "https://example.test/keibalab")

    runners = {runner.horse_no: runner for runner in keibalab.runners}
    assert [race.source_date for race in runners["16"].recent_races] == [date(2026, 6, 21), date(2026, 5, 31)]
    assert [race.source_date for race in runners["15"].recent_races] == [date(2026, 6, 14), date(2026, 5, 25)]
    assert runners["14"].recent_races == []
