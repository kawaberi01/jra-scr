from datetime import date

import pytest

from jra_srb.provider import BaseProvider, PageContent
from jra_srb.service import JraService


class HistoricalFallbackProvider(BaseProvider):
    async def check_upstream(self) -> PageContent:
        return PageContent(source="fake", content="ok")

    async def post_jradb(self, path: str, cname: str) -> PageContent:
        if path.endswith("accessD.html") and cname == "pw01dli00/F3":
            return PageContent(
                source="fake-accessD-select",
                content="<html><body><a onclick=\"doAction('/JRADB/accessD.html','pw01drl00062026020820260322/83')\">中山</a></body></html>",
            )
        if path.endswith("accessH.html") and cname == "pw01hli00/03":
            return PageContent(
                source="fake-accessH-select",
                content=(
                    "<html><body>"
                    "<a onclick=\"doAction('/JRADB/accessH.html','pw01hde01062026020820250105/2B')\">中山</a>"
                    "</body></html>"
                ),
            )
        if path.endswith("accessH.html") and cname == "pw01hde01062026020820250105/2B":
            return PageContent(
                source="fake-accessH-meeting",
                content=(
                    "<html><body><table><tbody><tr>"
                    "<th class='race_num'><a href='/JRADB/accessD.html?CNAME=pw01dde0106202602081120250105/F2'>11R</a></th>"
                    "<td class='race_name'><div><div>Sample Stakes</div></div></td>"
                    "<td class='time'>15:45</td>"
                    "<td class='odds'><a onclick=\"doAction('/JRADB/accessO.html','pw151ouS306202602081120250105Z/95')\">odds</a></td>"
                    "<td class='result'><a href='/JRADB/accessH.html?CNAME=pw01hde01062026020820250105/2B'>result</a></td>"
                    "</tr></tbody></table></body></html>"
                ),
            )
        raise AssertionError(f"unexpected post_jradb: {path} {cname}")

    async def fetch_jradb(self, path: str, cname: str) -> PageContent:
        if path.endswith("accessD.html") and cname == "pw01dde0106202602081120250105/F2":
            return PageContent(
                source="fake-accessD-race",
                content=(
                    "<html><body>"
                    "<div class='race_header'>"
                    "<div class='race_name'>Sample Stakes</div>"
                    "<div class='type'><span class='course'>芝 1200m</span></div>"
                    "<div class='date_line'><span class='time'><strong>15:45</strong></span></div>"
                    "</div>"
                    "<table class='basic narrow-xy mt20'><tbody>"
                    "<tr>"
                    "<td class='num'>1</td>"
                    "<td class='horse'>"
                    "<p class='name'><a href='#'>Horse A</a></p>"
                    "<p class='trainer'><a href='#'>Trainer A</a></p>"
                    "<p class='odds'><strong>3.4</strong></p>"
                    "<p class='pop_rank'>1人気</p>"
                    "</td>"
                    "<td class='jockey'>牡3/鹿 55.0 kg 騎手A</td>"
                    "</tr>"
                    "</tbody></table>"
                    "</body></html>"
                ),
            )
        raise AssertionError(f"unexpected fetch_jradb: {path} {cname}")

    async def fetch_races(self, target_date: date, course: str | None = None) -> PageContent:
        raise AssertionError("fetch_races should not be called")

    async def fetch_race_card(self, race_id: str) -> PageContent:
        raise AssertionError("fetch_race_card should not be called")

    async def fetch_race_odds(self, race_id: str) -> PageContent:
        raise AssertionError("fetch_race_odds should not be called")

    async def fetch_race_result(self, race_id: str) -> PageContent:
        raise AssertionError("fetch_race_result should not be called")

    async def fetch_calendar_month(self, year: int, month: int) -> PageContent:
        raise AssertionError("fetch_calendar_month should not be called")


@pytest.mark.asyncio
async def test_service_falls_back_to_payout_selection_for_historical_meeting():
    service = JraService(provider=HistoricalFallbackProvider())

    meeting = await service.get_meeting(date(2025, 1, 5), "nakayama")
    card = await service.get_race_card_by_number(date(2025, 1, 5), "nakayama", 11)

    assert len(meeting.races) == 1
    assert meeting.races[0].race_id == "202501050611"
    assert card.race_id == "202501050611"
    assert card.runners[0].jockey == "騎手A"


class CalendarFallbackProvider(BaseProvider):
    async def check_upstream(self) -> PageContent:
        return PageContent(source="fake", content="ok")

    async def post_jradb(self, path: str, cname: str) -> PageContent:
        if path.endswith("accessD.html") and cname == "pw01dli00/F3":
            return PageContent(source="fake-accessD-select", content="<html><body></body></html>")
        if path.endswith("accessH.html") and cname == "pw01hli00/03":
            return PageContent(source="fake-accessH-select", content="<html><body></body></html>")
        if path.endswith("accessS.html") and cname in {"pw01sli00/AF", "pw01skl00999999/B3"}:
            return PageContent(source="fake-accessS-select", content="<html><body></body></html>")
        raise AssertionError(f"unexpected post_jradb: {path} {cname}")

    async def fetch_calendar_month(self, year: int, month: int) -> PageContent:
        assert (year, month) == (2025, 1)
        return PageContent(
            source="fake-calendar",
            content=(
                '[{"month":"1","data":['
                '{"date":"5","day":"日曜","info":[{"race":[{"name":"1回中山"},{"name":"1回中京"}]}]},'
                '{"date":"6","day":"月曜","info":[{"race":[{"name":"1回中山"}]}]}'
                "]}]"
            ),
        )

    async def fetch_jradb(self, path: str, cname: str) -> PageContent:
        raise AssertionError("fetch_jradb should not be called")

    async def fetch_races(self, target_date: date, course: str | None = None) -> PageContent:
        raise AssertionError("fetch_races should not be called")

    async def fetch_race_card(self, race_id: str) -> PageContent:
        raise AssertionError("fetch_race_card should not be called")

    async def fetch_race_odds(self, race_id: str) -> PageContent:
        raise AssertionError("fetch_race_odds should not be called")

    async def fetch_race_result(self, race_id: str) -> PageContent:
        raise AssertionError("fetch_race_result should not be called")


@pytest.mark.asyncio
async def test_service_falls_back_to_calendar_for_historical_meetings():
    service = JraService(provider=CalendarFallbackProvider())

    meetings = await service.get_meetings_for_date(date(2025, 1, 5))

    assert [meeting.course for meeting in meetings] == ["nakayama", "chukyo"]
    assert meetings[0].races[0].race_id == "202501050601"
    assert meetings[0].races[-1].race_id == "202501050612"


class HistoricalResultCardFallbackProvider(BaseProvider):
    async def check_upstream(self) -> PageContent:
        return PageContent(source="fake", content="ok")

    async def post_jradb(self, path: str, cname: str) -> PageContent:
        if path.endswith("accessD.html") and cname == "pw01dli00/F3":
            return PageContent(source="fake-accessD-select", content="<html><body></body></html>")
        if path.endswith("accessH.html") and cname == "pw01hli00/03":
            return PageContent(source="fake-accessH-select", content="<html><body></body></html>")
        if path.endswith("accessS.html") and cname in {"pw01sli00/AF", "pw01skl00999999/B3"}:
            return PageContent(
                source="fake-accessS-select",
                content=(
                    "<html><body>"
                    "<a onclick=\"doAction('/JRADB/accessS.html','pw01srl10062025010120250105/AA')\">中山</a>"
                    "</body></html>"
                ),
            )
        if path.endswith("accessS.html") and cname == "pw01srl10062025010120250105/AA":
            return PageContent(
                source="fake-accessS-meeting",
                content=(
                    "<html><body>"
                    "<a href='/JRADB/accessS.html?CNAME=pw01sde1006202501011120250105/BD'>11R</a>"
                    "</body></html>"
                ),
            )
        if path.endswith("accessS.html") and cname == "pw01sde1006202501011120250105/BD":
            return PageContent(
                source="fake-accessS-race",
                content=(
                    "<html><body><div id='race_result'><div class='race_result_unit'>"
                    "<table><caption><div class='race_header'>"
                    "<div class='race_name'>Sample Stakes</div>"
                    "<div class='type'><span class='course'>2,000メートル（芝・右）</span></div>"
                    "<div class='date_line'><span class='time'><strong>15時45分</strong></span></div>"
                    "</div></caption><tbody><tr>"
                    "<td class='place'>1</td><td class='waku'>4</td><td class='num'>8</td>"
                    "<td class='horse'><a href='#'>Horse A</a></td>"
                    "<td class='age'>牡4</td><td class='weight'>57.5</td>"
                    "<td class='jockey'>Jockey A</td><td class='time'>1:58.1</td>"
                    "<td class='trainer'>Trainer A</td>"
                    "</tr></tbody></table></div></div></body></html>"
                ),
            )
        raise AssertionError(f"unexpected post_jradb: {path} {cname}")

    async def fetch_calendar_month(self, year: int, month: int) -> PageContent:
        return PageContent(
            source="fake-calendar",
            content='[{"month":"1","data":[{"date":"5","info":[{"race":[{"name":"1回中山"}]}]}]}]',
        )

    async def fetch_jradb(self, path: str, cname: str) -> PageContent:
        raise AssertionError("fetch_jradb should not be called when card cname is unavailable")

    async def fetch_races(self, target_date: date, course: str | None = None) -> PageContent:
        raise AssertionError("fetch_races should not be called")

    async def fetch_race_card(self, race_id: str) -> PageContent:
        raise AssertionError("fetch_race_card should not be called")

    async def fetch_race_odds(self, race_id: str) -> PageContent:
        raise AssertionError("fetch_race_odds should not be called")

    async def fetch_race_result(self, race_id: str) -> PageContent:
        raise AssertionError("fetch_race_result should not be called")


@pytest.mark.asyncio
async def test_service_builds_historical_card_from_result_page_when_card_cname_is_unavailable():
    service = JraService(provider=HistoricalResultCardFallbackProvider())

    card = await service.get_race_card_by_number(date(2025, 1, 5), "nakayama", 11)

    assert card.race_id == "202501050611"
    assert card.race_name == "Sample Stakes"
    assert card.surface == "芝"
    assert card.distance == "2,000"
    assert len(card.runners) == 1
    assert card.runners[0].horse_no == "8"
    assert card.runners[0].horse_name == "Horse A"
    assert card.runners[0].jockey == "Jockey A"
    assert card.runners[0].trainer == "Trainer A"
