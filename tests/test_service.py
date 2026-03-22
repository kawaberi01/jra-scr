from datetime import date

import pytest


@pytest.mark.asyncio
async def test_get_races(service):
    races = await service.get_races(date(2026, 3, 22))
    assert len(races) == 2
    assert races[0].race_id == "202603220101"
    assert races[0].name == "若葉ステークス"


@pytest.mark.asyncio
async def test_get_race_card(service):
    card = await service.get_race_card("202603220101")
    assert card.race_name == "若葉ステークス"
    assert len(card.runners) == 2
    assert card.runners[0].horse_name == "サンプルホースA"


@pytest.mark.asyncio
async def test_get_race_odds(service):
    odds = await service.get_race_odds("202603220101", bet_types=["win", "trifecta"])
    assert set(odds.odds) == {"win", "trifecta"}
    assert odds.odds["win"][0].combination == ["1"]
    assert odds.odds["trifecta"][0].combination == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_get_race_odds_for_single_bet_type(service):
    odds = await service.get_race_odds("202603220611", bet_type="trifecta")
    assert odds.bet_type == "trifecta"
    assert odds.entries
    assert all(len(item.combination) == 3 for item in odds.entries)


@pytest.mark.asyncio
async def test_filter_odds_by_exact_combination(service):
    odds = await service.get_race_odds(
        "202603220611",
        bet_type="trifecta",
        combination=["1", "2", "3"],
    )
    assert len(odds.entries) == 1
    assert odds.entries[0].combination == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_get_result_by_meeting_coordinates(service):
    result = await service.get_race_result_by_number(
        target_date=date(2026, 3, 22),
        course="nakayama",
        race_no=11,
    )
    assert result.race_id == "202603220611"
    assert result.race_name == "千葉ステークス"
    assert result.results[0].horse_name == "ドラゴンウェルズ"
    assert any(p.bet_type == "3連単" and p.combination == "10-11-4" for p in result.payouts)


@pytest.mark.asyncio
async def test_get_race_result(service):
    result = await service.get_race_result("202603220101")
    assert result.race_name == "若葉ステークス"
    assert result.results[0].horse_name == "サンプルホースA"
    assert result.payouts[0].bet_type == "単勝"


@pytest.mark.asyncio
async def test_get_meeting_returns_twelve_races(service):
    meeting = await service.get_meeting(date(2026, 3, 22), "nakayama")
    assert meeting.course == "nakayama"
    assert len(meeting.races) == 12
    assert meeting.races[10].race_no == 11
    assert meeting.races[10].race_id == "202603220611"
    assert meeting.races[10].race_name == "千葉ステークス"


@pytest.mark.asyncio
async def test_get_race_card_by_meeting_coordinates(service):
    card = await service.get_race_card_by_number(
        target_date=date(2026, 3, 22),
        course="nakayama",
        race_no=11,
    )
    assert card.race_id == "202603220611"
    assert card.race_name == "千葉ステークス"
    assert len(card.runners) == 16
    assert card.runners[0].horse_name == "ジャスパーゴールド"


@pytest.mark.asyncio
async def test_cache_hit(service):
    first = await service.get_race_card("202603220101")
    second = await service.get_race_card("202603220101")
    assert first.cache_hit is False
    assert second.cache_hit is True
