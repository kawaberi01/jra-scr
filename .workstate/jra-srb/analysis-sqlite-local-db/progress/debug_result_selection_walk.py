from datetime import date
import sys

from jra_srb.extractors import parse_result_month_navigation
from jra_srb.navigation import JraNavigation
from jra_srb.provider import HttpProvider
from jra_srb.service import JraService


async def main():
    provider = HttpProvider()
    navigation = JraNavigation()
    target_date = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2025, 1, 5)
    target_month = f"{target_date.year:04d}-{target_date.month:02d}"
    page = await provider.post_jradb("/JRADB/accessS.html", "pw01sli00/AF")
    print("step=0")
    print("meetings", len(navigation.list_meetings_from_selection(page, target_date, kind="result")))
    print("months", parse_result_month_navigation(page.content))
    if not parse_result_month_navigation(page.content):
        page = await provider.post_jradb("/JRADB/accessS.html", "pw01skl00999999/B3")
        print("step=0.5")
        print("meetings", len(navigation.list_meetings_from_selection(page, target_date, kind="result")))
        print("months", parse_result_month_navigation(page.content))
    visited = set()
    for step in range(1, 16):
        month_navigation = parse_result_month_navigation(page.content)
        next_cname = JraService._select_closest_result_month_cname(month_navigation, target_month, visited)
        print(f"step={step}", "next", next_cname)
        if next_cname is None:
            break
        visited.add(next_cname)
        page = await provider.post_jradb("/JRADB/accessS.html", next_cname)
        meetings = navigation.list_meetings_from_selection(page, target_date, kind="result")
        print("meetings", len(meetings))
        print("months", month_navigation)
        if meetings:
            for meeting in meetings:
                print("meeting", repr(meeting).encode("unicode_escape").decode("ascii"))
            break


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
