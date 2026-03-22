from datetime import date
from pathlib import Path

import pytest

from jra_srb.provider import PageContent


def _load(name: str) -> str:
    return (Path(__file__).parent / "fixtures" / name).read_text(encoding="shift_jis")


@pytest.mark.asyncio
async def test_find_meeting_link_for_course_and_date():
    from jra_srb.navigation import JraNavigation

    nav = JraNavigation()
    page = PageContent(source="fixture", content=_load("jradb_accessD_select.html"))

    resolved = nav.resolve_meeting_from_selection(
        page=page,
        target_date=date(2026, 3, 22),
        course="nakayama",
        kind="card",
    )

    assert resolved.cname.startswith("pw01drl")
    assert resolved.label == "2回中山8日"


@pytest.mark.asyncio
async def test_find_result_meeting_link_for_course_and_date():
    from jra_srb.navigation import JraNavigation

    nav = JraNavigation()
    page = PageContent(source="fixture", content=_load("jradb_accessS_select.html"))

    resolved = nav.resolve_meeting_from_selection(
        page=page,
        target_date=date(2026, 3, 22),
        course="hanshin",
        kind="result",
    )

    assert resolved.cname.startswith("pw01srl")
    assert resolved.label == "1回阪神10日"
