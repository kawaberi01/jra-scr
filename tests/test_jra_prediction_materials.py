from datetime import UTC, date, datetime
from pathlib import Path

from jra_srb.jra_prediction_materials import (
    build_best_time_lite,
    build_closing_speed_lite,
    build_source_keys,
    build_style_profile_lite,
)
from jra_srb.jra_public_analysis_extractors import (
    parse_keibalab_umabashira,
    parse_netkeiba_data_top,
    parse_umanity_race,
)
from jra_srb.models import JraMaterialStatus, JraPublicAnalysis, RaceCard, Runner


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


def test_lite_materials_use_official_recent_races_when_public_runner_is_missing():
    now = datetime.now(UTC)
    card = RaceCard(
        race_id="202608020407",
        course="niigata",
        surface="芝",
        distance="1000",
        runners=[
            Runner(
                horse_no="17",
                horse_name="テストホース",
                official_recent_races=[
                    {
                        "source_date": date(2026, 6, 1),
                        "source_course": "新潟",
                        "surface": "芝",
                        "distance": 1000,
                        "track_condition": "良",
                        "finish_rank": 2,
                        "field_size": 18,
                        "finish_time": "0:54.5",
                        "final_3f": 32.1,
                        "corner_positions": [2],
                        "source": "jra_official_card",
                    }
                ],
            )
        ],
        fetched_at=now,
        source="jra_official",
    )
    public = JraPublicAnalysis(
        race_id=card.race_id,
        date=date(2026, 8, 2),
        course="niigata",
        race_no=7,
        meeting_no=2,
        meeting_day=4,
        status=JraMaterialStatus.unavailable,
        sources={},
        fetched_at=now,
        source_keys=build_source_keys(date(2026, 8, 2), "niigata", 7, 2, 4),
    )

    materials = [
        build_best_time_lite(card, public),
        build_closing_speed_lite(card, public),
        build_style_profile_lite(card, public),
    ]

    assert all(material.status == JraMaterialStatus.available for material in materials)
    assert all(material.runners[0].source_race.source == "jra_official_card" for material in materials)
    assert all(material.source == "jra_official_card+public_race_pages" for material in materials)
