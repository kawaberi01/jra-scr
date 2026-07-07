from datetime import date

import pytest

from jra_srb.errors import BadRequestError, ResourceNotFoundError
from jra_srb.nankan_provider import NankanFixtureProvider, NankanPageContent
from jra_srb.nankan_service import NankanService


@pytest.mark.asyncio
async def test_nankan_service_get_meeting_and_card():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    meeting = await service.get_meeting(date(2026, 7, 4), "funabashi")
    card = await service.get_race_card_by_number(date(2026, 7, 4), "funabashi", 1)

    assert meeting.races[0].race_id == "2026070419040501"
    assert card.race_id == "2026070419040501"
    assert card.runners[0].horse_name == "トーセンレクサム"


@pytest.mark.asyncio
async def test_nankan_service_get_odds_filters_combination():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    odds = await service.get_race_odds("2026070419040501", bet_type="wide", combination=["2", "1"])

    assert odds.bet_type == "wide"
    assert odds.odds == {}
    assert len(odds.entries) == 1
    assert odds.entries[0].combination == ["1", "2"]
    assert odds.entries[0].odds_min == "33.3"


@pytest.mark.asyncio
async def test_nankan_service_get_result():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    result = await service.get_race_result("2026070419040501")

    assert result.race_id == "2026070419040501"
    assert result.results[0].horse_name == "イデスホープ"
    assert result.payouts[0].bet_type == "win"
    assert result.payouts[-1].bet_type == "trifecta"


@pytest.mark.asyncio
async def test_nankan_service_get_result_by_number():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    result = await service.get_race_result_by_number(date(2026, 7, 4), "funabashi", 1)

    assert result.race_id == "2026070419040501"
    assert result.results[0].rank == "1"


@pytest.mark.asyncio
async def test_nankan_service_get_kawasaki_result_by_number():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    result = await service.get_race_result_by_number(date(2026, 7, 6), "kawasaki", 1)

    assert result.race_id == "2026070621040101"
    assert result.results[0].horse_name == "ヘヴンリーゴール"
    assert result.payouts[-1].bet_type == "trifecta"


@pytest.mark.asyncio
async def test_nankan_service_get_kawasaki_11r_card_keeps_horse_no_9():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    card = await service.get_race_card_by_number(date(2026, 7, 6), "kawasaki", 11)

    assert card.race_id == "2026070621040111"
    assert card.race_name == "アクルックス賞"
    assert card.surface == "dirt"
    assert card.surface_label == "ダ"
    assert card.distance == "2000"
    assert card.start_time == "20:15"
    assert card.weather == "rainy"
    assert card.weather_label == "雨"
    assert card.track_condition == "heavy"
    assert card.track_condition_label == "重"
    assert [runner.horse_no for runner in card.runners] == [str(number) for number in range(1, 10)]


@pytest.mark.asyncio
async def test_nankan_service_get_kawasaki_11r_card_by_race_id_merges_conditions():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    card = await service.get_race_card("2026070621040111")

    assert card.race_id == "2026070621040111"
    assert card.weather == "rainy"
    assert card.track_condition == "heavy"
    assert card.surface == "dirt"
    assert card.distance == "2000"
    assert card.start_time == "20:15"


@pytest.mark.asyncio
async def test_nankan_service_get_meeting_trend():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    trend = await service.get_meeting_trend(date(2026, 7, 6), "kawasaki")

    assert trend.date == date(2026, 7, 6)
    assert trend.course == "kawasaki"
    assert trend.meeting_id == "2026210401"
    assert trend.open_date == "20260706"
    assert trend.race_count_completed == 12
    assert trend.updated_at is not None
    assert trend.updated_at.isoformat() == "2026-07-06T21:24:00+09:00"
    assert trend.summary.frame[0].frame_no == "6"
    assert trend.summary.running_style.front_group_top3_count == 27
    assert trend.summary.jockey[0].name == "笹川翼"
    assert trend.summary.trainer[0].name == "高月賢一"
    assert trend.summary.payout.trifecta_max_payout == 109080


@pytest.mark.asyncio
async def test_nankan_service_get_best_time_by_number():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    best_time = await service.get_race_best_time_by_number(date(2026, 7, 6), "kawasaki", 1)

    assert best_time.race_id == "2026070621040101"
    assert best_time.course == "kawasaki"
    assert best_time.distance == 1400
    assert best_time.surface == "dirt"
    assert best_time.runners[0].horse_no == "5"
    assert best_time.runners[0].best_time == "1:31.8"
    assert best_time.runners[0].same_course_flag is True
    assert best_time.runners[1].same_distance_flag is False


@pytest.mark.asyncio
async def test_nankan_service_get_closing_speed_by_number():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    closing = await service.get_race_closing_speed_by_number(date(2026, 7, 6), "kawasaki", 1)

    assert closing.race_id == "2026070621040101"
    assert closing.distance == 1400
    assert closing.runners[0].horse_no == "5"
    assert closing.runners[0].best_closing_time == "39.5"
    assert closing.runners[0].closing_section_distance == 600


@pytest.mark.asyncio
async def test_nankan_service_get_style_profile_by_number():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    profile = await service.get_race_style_profile_by_number(date(2026, 7, 6), "kawasaki", 1)

    assert profile.race_id == "2026070621040101"
    assert profile.runners[0].horse_no == "5"
    assert profile.runners[0].sample_size == 2
    assert profile.runners[0].expected_style == "front"
    assert profile.runners[0].style_scores.front == 0.5
    assert profile.runners[0].style_scores.midpack == 0.5
    assert profile.runners[0].recent_races[0].corner_positions == [7, 7, 4]
    assert profile.runners[1].expected_style == "closer"


@pytest.mark.asyncio
async def test_nankan_service_get_leading_jockeys():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    page = await service.get_leading_jockeys(
        course="kawasaki",
        distance=1400,
        track_condition="good",
        period="recent_3months",
        sort="win_rate",
    )

    assert page.source == "nankankeiba"
    assert page.course == "kawasaki"
    assert page.distance == 1400
    assert page.track_condition == "good"
    assert page.period == "recent_3months"
    assert page.sort == "win_rate"
    assert page.items[0].jockey_name == "野畑凌"
    assert page.items[0].win_rate == 20.0


@pytest.mark.asyncio
async def test_nankan_service_get_leading_jockeys_changes_by_track_condition():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    good = await service.get_leading_jockeys(course="kawasaki", distance=1400, track_condition="good")
    bad = await service.get_leading_jockeys(course="kawasaki", distance=1400, track_condition="bad")

    assert good.items[0].jockey_name != bad.items[0].jockey_name


@pytest.mark.asyncio
async def test_nankan_service_get_leading_jockeys_changes_by_period():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    recent_3months = await service.get_leading_jockeys(course="kawasaki", distance=1400, track_condition="good")
    recent_1year = await service.get_leading_jockeys(
        course="kawasaki",
        distance=1400,
        track_condition="good",
        period="recent_1year",
    )

    assert recent_3months.items[0].jockey_name != recent_1year.items[0].jockey_name


@pytest.mark.asyncio
async def test_nankan_service_get_leading_jockeys_empty_items():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    page = await service.get_leading_jockeys()

    assert page.items == []


@pytest.mark.asyncio
async def test_nankan_service_get_leading_jockeys_kawasaki_2026_url_patterns():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    overall = await service.get_leading_jockeys(course="kawasaki", period="2026", sort="wins")
    distance = await service.get_leading_jockeys(course="kawasaki", distance=900, period="2026", sort="wins")
    good = await service.get_leading_jockeys(
        course="kawasaki",
        distance=900,
        track_condition="good",
        period="2026",
        sort="wins",
    )

    assert overall.requested_condition_code == "210000002026011"
    assert overall.effective_condition_code == "210000002026011"
    assert overall.fallback is False
    assert overall.items[0].jockey_name == "川崎総合騎手"
    assert distance.requested_condition_code == "210900002026011"
    assert distance.items[0].jockey_name == "川崎900騎手"
    assert good.requested_condition_code == "210900012026011"
    assert good.track_condition == "good"
    assert good.items[0].jockey_name == "川崎900良騎手"


@pytest.mark.asyncio
async def test_nankan_service_get_leading_jockeys_track_condition_codes():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    cases = [
        ("good", "210900012026011"),
        ("slightly_heavy", "210900022026011"),
        ("heavy", "210900032026011"),
        ("bad", "210900042026011"),
    ]

    for track_condition, expected_code in cases:
        page = await service.get_leading_jockeys(
            course="kawasaki",
            distance=900,
            track_condition=track_condition,
            period="2026",
            sort="wins",
        )
        assert page.requested_condition_code == expected_code
        assert page.effective_condition_code == expected_code
        assert page.fallback is False
        assert page.track_condition == track_condition
        assert page.items


class MissingLeadingJockeysProvider(NankanFixtureProvider):
    async def fetch_leading_jockeys(self, condition_code: str) -> NankanPageContent:
        if condition_code == "210900012026011":
            raise ResourceNotFoundError(f"fixture not found: {condition_code}")
        return await super().fetch_leading_jockeys(condition_code)


@pytest.mark.asyncio
async def test_nankan_service_get_leading_jockeys_marks_fallback():
    service = NankanService(provider=MissingLeadingJockeysProvider("tests/fixtures"))

    page = await service.get_leading_jockeys(
        course="kawasaki",
        distance=900,
        track_condition="good",
        period="2026",
        sort="wins",
    )

    assert page.requested_condition_code == "210900012026011"
    assert page.effective_condition_code == "000000000000001"
    assert page.fallback is True
    assert page.items == []


@pytest.mark.asyncio
async def test_nankan_service_rejects_unsupported_leading_distance():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    with pytest.raises(BadRequestError):
        await service.get_leading_jockeys(distance=1150)


@pytest.mark.asyncio
async def test_nankan_service_rejects_unsupported_bet_type():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    with pytest.raises(BadRequestError):
        await service.get_race_odds("2026070419040501", bet_type="bracket_quinella")


class MissingOddsProvider(NankanFixtureProvider):
    async def fetch_odds(self, race_id: str, bet_type: str) -> NankanPageContent:
        raise ResourceNotFoundError(f"nankan odds not available yet: race_id={race_id} bet_type={bet_type}")


class MissingResultProvider(NankanFixtureProvider):
    async def fetch_result(self, race_id: str) -> NankanPageContent:
        raise ResourceNotFoundError(f"nankan result not available yet: race_id={race_id}")


@pytest.mark.asyncio
async def test_nankan_service_propagates_not_available_404():
    service = NankanService(provider=MissingOddsProvider("tests/fixtures"))

    with pytest.raises(ResourceNotFoundError, match="odds not available yet"):
        await service.get_race_odds("2026070419040501", bet_type="win", refresh=True)


@pytest.mark.asyncio
async def test_nankan_service_propagates_result_not_available_404():
    service = NankanService(provider=MissingResultProvider("tests/fixtures"))

    with pytest.raises(ResourceNotFoundError, match="result not available yet"):
        await service.get_race_result("2026070419040501", refresh=True)
