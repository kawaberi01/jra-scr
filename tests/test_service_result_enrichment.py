from datetime import date

import pytest


@pytest.mark.asyncio
async def test_get_result_by_meeting_coordinates_enriches_missing_jockey_from_card(service):
    card = await service.get_race_card_by_number(
        target_date=date(2026, 3, 22),
        course="nakayama",
        race_no=11,
    )
    result = await service.get_race_result_by_number(
        target_date=date(2026, 3, 22),
        course="nakayama",
        race_no=11,
    )

    jockey_by_horse_no = {runner.horse_no: runner.jockey for runner in card.runners}

    assert result.results
    assert result.results[0].horse_no in jockey_by_horse_no
    assert result.results[0].jockey is not None
    assert result.results[0].jockey.replace(" ", "") == jockey_by_horse_no[result.results[0].horse_no]
