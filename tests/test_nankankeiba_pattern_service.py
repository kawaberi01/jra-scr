from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from jra_srb.app import app, get_nankankeiba_pattern_service
from jra_srb.cache import SQLiteTTLCache
from jra_srb.models import NankankeibaPatternCategoryEntry, NankankeibaPatternCategoryPage
from jra_srb.nankankeiba_pattern_provider import (
    BaseNankankeibaPatternProvider,
    NankankeibaPatternFixtureProvider,
    NankankeibaPatternPageContent,
)
from jra_srb.nankankeiba_pattern_service import NankankeibaPatternService, _merge_category_pages


@pytest.mark.asyncio
async def test_get_pattern_category_from_fixture():
    service = NankankeibaPatternService(provider=NankankeibaPatternFixtureProvider("tests/fixtures"))

    page = await service.get_pattern_category(date(2026, 7, 6), "kawasaki", 4, 1, 1, "pattern_kis")

    assert page.race_id == "202607062104010101"
    assert page.category == "pattern_kis"
    assert len(page.entries) == 7
    assert page.entries[0].horse_name == "ヴェロス"
    assert page.entries[0].rates["lifetime"].wins == 137


@pytest.mark.asyncio
async def test_get_pattern_bundle_merges_four_categories_by_horse_no():
    service = NankankeibaPatternService(provider=NankankeibaPatternFixtureProvider("tests/fixtures"))

    bundle = await service.get_pattern_bundle(date(2026, 7, 6), "kawasaki", 4, 1, 1)

    assert bundle.race_id == "202607062104010101"
    assert bundle.periods == ["01"]
    assert bundle.categories == ["pattern_kis", "pattern_uma", "pattern_cho", "pattern_kis_cho"]
    assert len(bundle.runners) == 7
    assert bundle.runners[4].horse_no == "5"
    assert set(bundle.runners[4].categories) == set(bundle.categories)
    assert bundle.runners[4].categories["pattern_kis"].rates["kawasaki"].rate == 14.5
    assert bundle.runners[4].categories["pattern_uma"].rates["medium"].rate == 16.7
    assert bundle.runners[4].categories["pattern_uma"].rates["short"].rate == 50.0
    assert bundle.runners[4].categories["pattern_uma"].track_condition_rates["good"].rate == 33.3


@pytest.mark.asyncio
async def test_get_pattern_category_uses_db_first_ttl_cache(tmp_path):
    provider = CountingPatternProvider("tests/fixtures")
    service = NankankeibaPatternService(
        provider=provider,
        cache=SQLiteTTLCache(tmp_path / "cache.sqlite"),
    )

    first = await service.get_pattern_category(date(2026, 7, 6), "kawasaki", 4, 1, 1, "pattern_kis")
    second = await service.get_pattern_category(date(2026, 7, 6), "kawasaki", 4, 1, 1, "pattern_kis")

    assert provider.calls == 1
    assert first.meta is not None
    assert first.meta.data_source == "external"
    assert first.meta.saved is True
    assert second.cache_hit is True
    assert second.meta is not None
    assert second.meta.data_source == "db"
    assert second.meta.db_hit is True


@pytest.mark.asyncio
async def test_get_pattern_category_refresh_true_forces_external_fetch(tmp_path):
    provider = CountingPatternProvider("tests/fixtures")
    service = NankankeibaPatternService(
        provider=provider,
        cache=SQLiteTTLCache(tmp_path / "cache.sqlite"),
    )

    await service.get_pattern_category(date(2026, 7, 6), "kawasaki", 4, 1, 1, "pattern_kis")
    refreshed = await service.get_pattern_category(
        date(2026, 7, 6),
        "kawasaki",
        4,
        1,
        1,
        "pattern_kis",
        refresh=True,
    )

    assert provider.calls == 2
    assert refreshed.meta is not None
    assert refreshed.meta.data_source == "external"
    assert refreshed.meta.db_hit is True
    assert refreshed.meta.saved is True


def test_merge_category_pages_sorts_numeric_horse_no_before_non_numeric():
    page = NankankeibaPatternCategoryPage(
        race_id="202607062104010801",
        category="pattern_uma",
        entries=[
            _entry("10", "十番"),
            _entry("2", "二番"),
            _entry("取 消", "取消馬"),
            _entry("1", "一番"),
        ],
        fetched_at=datetime.now(UTC),
        source="fixture",
    )

    runners = _merge_category_pages([page])

    assert [runner.horse_no for runner in runners] == ["1", "2", "10", "取 消"]


def test_nankankeiba_pattern_api_returns_200_when_cancelled_horse_no_is_mixed():
    service = NankankeibaPatternService(provider=CancelledHorsePatternProvider())
    app.dependency_overrides[get_nankankeiba_pattern_service] = lambda: service
    try:
        response = TestClient(app).get(
            "/nankankeiba/pattern/meetings/2026-07-06/kawasaki/races/8?meeting_no=4&meeting_day=1"
        )
        assert response.status_code == 200
        body = response.json()
        assert [runner["horse_no"] for runner in body["runners"]] == ["1", "2", "10", "取 消"]
        assert body["runners"][-1]["horse_name"] == "取消馬"
    finally:
        app.dependency_overrides.clear()


def _entry(horse_no: str, horse_name: str) -> NankankeibaPatternCategoryEntry:
    return NankankeibaPatternCategoryEntry(
        category="pattern_uma",
        frame_no="1",
        horse_no=horse_no,
        horse_name=horse_name,
    )


class CancelledHorsePatternProvider(BaseNankankeibaPatternProvider):
    async def fetch_pattern(self, race_id: str, category: str) -> NankankeibaPatternPageContent:
        return NankankeibaPatternPageContent(source=f"fixture:{category}:{race_id}", content=_pattern_html())


class CountingPatternProvider(NankankeibaPatternFixtureProvider):
    def __init__(self, fixtures_dir: str) -> None:
        super().__init__(fixtures_dir)
        self.calls = 0

    async def fetch_pattern(self, race_id: str, category: str) -> NankankeibaPatternPageContent:
        self.calls += 1
        return await super().fetch_pattern(race_id, category)


def _pattern_html() -> str:
    rows = "\n".join(
        _pattern_row(horse_no, horse_name)
        for horse_no, horse_name in [
            ("10", "十番"),
            ("2", "二番"),
            ("取 消", "取消馬"),
            ("1", "一番"),
        ]
    )
    return f"""
    <html>
      <body>
        <table class="nk23_c-table13__table">
          {rows}
        </table>
      </body>
    </html>
    """


def _pattern_row(horse_no: str, horse_name: str) -> str:
    cells = [
        "<td>1</td>",
        f"<td>{horse_no}</td>",
        f"<td><span>dummy</span><span>{horse_name}</span></td>",
        "<td>騎手<br>56.0<br>厩舎</td>",
        "<td>1.0</td>",
    ]
    cells.extend("<td>0.0% (0/0)</td>" for _ in range(25))
    return f"<tr class=\"win_pattern_data\">{''.join(cells)}</tr>"
