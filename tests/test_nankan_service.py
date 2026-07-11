import asyncio
from datetime import UTC, date, datetime

import pytest

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.cache import SQLiteTTLCache
from jra_srb.errors import BadRequestError, ResourceNotFoundError
from jra_srb.models import RaceCard, Runner
from jra_srb.nankankeiba_pattern_provider import NankankeibaPatternFixtureProvider
from jra_srb.nankankeiba_pattern_service import NankankeibaPatternService
from jra_srb.nankan_prediction_service import NankanPredictionService
from jra_srb.nankan_provider import NANKAN_BET_TYPE_TO_ODDS_CODE, NankanFixtureProvider, NankanPageContent
from jra_srb.nankan_service import NankanCacheTtls, NankanService


@pytest.mark.asyncio
async def test_nankan_service_get_meeting_and_card():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    meeting = await service.get_meeting(date(2026, 7, 4), "funabashi")
    card = await service.get_race_card_by_number(date(2026, 7, 4), "funabashi", 1)

    assert meeting.races[0].race_id == "2026070419040501"
    assert card.race_id == "2026070419040501"
    assert card.runners[0].horse_name == "トーセンレクサム"
    assert card.data_status is not None
    assert card.data_status.horse_weight == "available"


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
async def test_nankan_service_get_meeting_trend_context_rejects_future_snapshot_for_6r():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    context = await service.get_meeting_trend_context(date(2026, 7, 6), "kawasaki", 6)

    assert context.race_no == 6
    assert context.race_count_completed == 12
    assert context.required_max_completed == 5
    assert context.usable is False
    assert context.reason == "latest trend is post-race snapshot"
    assert context.summary.frame == []
    assert context.trend is not None
    assert context.trend.summary.frame[0].frame_no == "6"
    assert context.cache_hit is False


@pytest.mark.asyncio
async def test_nankan_service_get_meeting_trend_context_rejects_future_snapshot_for_1r():
    service = NankanService(provider=NankanFixtureProvider("tests/fixtures"))

    context = await service.get_meeting_trend_context(date(2026, 7, 6), "kawasaki", 1)

    assert context.race_count_completed == 12
    assert context.required_max_completed == 0
    assert context.usable is False


@pytest.mark.asyncio
async def test_nankan_service_get_meeting_trend_context_allows_empty_prerace_snapshot():
    service = NankanService(provider=MissingTrendProvider("tests/fixtures"))

    context = await service.get_meeting_trend_context(date(2026, 7, 6), "kawasaki", 1)

    assert context.race_count_completed == 0
    assert context.required_max_completed == 0
    assert context.usable is True
    assert context.reason is None
    assert context.cache_hit is False


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


class MissingTrendProvider(NankanFixtureProvider):
    async def fetch_trend(self, meeting_id: str, open_date: str) -> NankanPageContent:
        raise ResourceNotFoundError(f"nankan trend not available yet: meeting_id={meeting_id} open_date={open_date}")


class CountingCardProvider(NankanFixtureProvider):
    def __init__(self, fixtures_dir: str) -> None:
        super().__init__(fixtures_dir)
        self.card_calls = 0

    async def fetch_race_card(self, race_id: str) -> NankanPageContent:
        self.card_calls += 1
        return await super().fetch_race_card(race_id)


class CountingBundleProvider(NankanFixtureProvider):
    def __init__(self, fixtures_dir: str) -> None:
        super().__init__(fixtures_dir)
        self.card_calls = 0
        self.odds_calls: list[str] = []
        self.best_calls: list[str] = []

    async def fetch_race_card(self, race_id: str) -> NankanPageContent:
        self.card_calls += 1
        return await super().fetch_race_card(race_id)

    async def fetch_odds(self, race_id: str, bet_type: str) -> NankanPageContent:
        self.odds_calls.append(bet_type)
        odds_code = NANKAN_BET_TYPE_TO_ODDS_CODE[bet_type]
        return self._load(f"nankan_odds_2026070419040501{odds_code}.html")

    async def fetch_best(self, race_id: str, suffix: str) -> NankanPageContent:
        self.best_calls.append(suffix)
        return await super().fetch_best(race_id, suffix)


class ConcurrentPatternProvider(NankankeibaPatternFixtureProvider):
    def __init__(self, fixture_dir: str) -> None:
        super().__init__(fixture_dir)
        self.active_calls = 0
        self.max_active_calls = 0

    async def fetch_pattern(self, race_id: str, category: str):
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            await asyncio.sleep(0.01)
            return await super().fetch_pattern(race_id, category)
        finally:
            self.active_calls -= 1


class MissingCardProvider(NankanFixtureProvider):
    async def fetch_race_card(self, race_id: str) -> NankanPageContent:
        raise ResourceNotFoundError(f"nankan card not available yet: race_id={race_id}")


class UnpublishedWeightCardProvider(NankanFixtureProvider):
    async def fetch_race_card(self, race_id: str) -> NankanPageContent:
        return NankanPageContent(source=f"fixture:{race_id}", content=_unpublished_weight_card_html())


@pytest.mark.asyncio
async def test_nankan_service_returns_db_cache_when_ttl_is_valid(tmp_path):
    provider = CountingCardProvider("tests/fixtures")
    service = NankanService(provider=provider, cache=SQLiteTTLCache(tmp_path / "cache.sqlite"))

    first = await service.get_race_card("2026070419040501")
    second = await service.get_race_card("2026070419040501")

    assert provider.card_calls == 1
    assert first.meta is not None
    assert first.meta.data_source == "external"
    assert first.meta.saved is True
    assert second.cache_hit is True
    assert second.meta is not None
    assert second.meta.data_source == "db"
    assert second.meta.db_hit is True
    assert second.meta.ttl_expired is False


@pytest.mark.asyncio
async def test_nankan_service_backfills_data_status_for_legacy_cached_card(tmp_path):
    cache = SQLiteTTLCache(tmp_path / "cache.sqlite")
    legacy_card = RaceCard(
        race_id="2026070721040201",
        race_name="legacy",
        runners=[
            Runner(horse_no="1", horse_name="テストホースA"),
            Runner(horse_no="2", horse_name="テストホースB"),
        ],
        fetched_at=datetime.now(UTC),
        source="legacy-cache",
        data_status=None,
    )
    cache.set("nankan:card:2026070721040201", legacy_card, ttl_seconds=60)
    service = NankanService(provider=MissingCardProvider("tests/fixtures"), cache=cache)

    card = await service.get_race_card("2026070721040201")

    assert card.cache_hit is True
    assert card.data_status is not None
    assert card.data_status.horse_weight == "unpublished"
    assert card.data_status.horse_weight_reason == "all runners have null horse_weight before official publication"


@pytest.mark.asyncio
async def test_nankan_service_refetches_when_ttl_is_expired(tmp_path):
    cache = SQLiteTTLCache(tmp_path / "cache.sqlite")
    provider = CountingCardProvider("tests/fixtures")
    service = NankanService(provider=provider, cache=cache, ttl_config=NankanCacheTtls(card=60))
    stale = await service.get_race_card("2026070419040501")
    cache.set("nankan:card:2026070419040501", stale, ttl_seconds=-1)

    refreshed = await service.get_race_card("2026070419040501")

    assert provider.card_calls == 2
    assert refreshed.meta is not None
    assert refreshed.meta.data_source == "external"
    assert refreshed.meta.db_hit is True
    assert refreshed.meta.ttl_expired is True
    assert refreshed.meta.saved is True


@pytest.mark.asyncio
async def test_nankan_service_refresh_true_forces_external_fetch(tmp_path):
    provider = CountingCardProvider("tests/fixtures")
    service = NankanService(provider=provider, cache=SQLiteTTLCache(tmp_path / "cache.sqlite"))

    await service.get_race_card("2026070419040501")
    refreshed = await service.get_race_card("2026070419040501", refresh=True)

    assert provider.card_calls == 2
    assert refreshed.meta is not None
    assert refreshed.meta.data_source == "external"
    assert refreshed.meta.db_hit is True
    assert refreshed.meta.saved is True


@pytest.mark.asyncio
async def test_nankan_service_returns_stale_db_data_when_refresh_fails(tmp_path):
    cache = SQLiteTTLCache(tmp_path / "cache.sqlite")
    service = NankanService(provider=CountingCardProvider("tests/fixtures"), cache=cache)
    stale = await service.get_race_card("2026070419040501")
    cache.set("nankan:card:2026070419040501", stale, ttl_seconds=-1)

    failing_service = NankanService(provider=MissingCardProvider("tests/fixtures"), cache=cache)
    result = await failing_service.get_race_card("2026070419040501")

    assert result.race_id == "2026070419040501"
    assert result.meta is not None
    assert result.meta.data_source == "db"
    assert result.meta.db_hit is True
    assert result.meta.ttl_expired is True
    assert result.meta.stale is True
    assert "card not available yet" in (result.meta.refresh_error or "")


@pytest.mark.asyncio
async def test_nankan_service_marks_unpublished_horse_weight():
    service = NankanService(provider=UnpublishedWeightCardProvider("tests/fixtures"))

    card = await service.get_race_card("2026070721040201")

    assert card.data_status is not None
    assert card.data_status.horse_weight == "unpublished"
    assert card.data_status.horse_weight_reason == "all runners have null horse_weight before official publication"
    assert all(runner.horse_weight is None for runner in card.runners)
    assert all(runner.horse_weight_diff is None for runner in card.runners)


@pytest.mark.asyncio
async def test_nankan_service_writes_external_odds_to_analysis_snapshots(tmp_path):
    store = AnalysisSQLiteStore(tmp_path / "analysis.sqlite")
    service = NankanService(
        provider=NankanFixtureProvider("tests/fixtures"),
        cache=SQLiteTTLCache(tmp_path / "cache.sqlite"),
        analysis_store=store,
    )

    odds = await service.get_race_odds("2026070419040501", bet_type="win")

    assert odds.meta is not None
    assert odds.meta.saved is True
    assert store.count_rows("odds_snapshots") == 1
    assert store.count_rows("odds_entries") == len(odds.entries)


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


@pytest.mark.asyncio
async def test_nankan_prediction_bundle_reuses_card_and_shared_odds_page():
    provider = CountingBundleProvider("tests/fixtures")
    prediction_service = NankanPredictionService(
        nankan_service=NankanService(provider=provider),
        pattern_service=NankankeibaPatternService(provider=NankankeibaPatternFixtureProvider("tests/fixtures")),
    )

    bundle = await prediction_service.get_prediction_bundle(
        date(2026, 7, 6),
        "kawasaki",
        1,
        4,
        1,
    )

    assert bundle.card.race_id == "2026070621040101"
    assert provider.card_calls == 1
    assert provider.odds_calls == ["win", "wide"]
    assert sorted(provider.best_calls) == ["000000", "221400"]


@pytest.mark.asyncio
async def test_nankan_prediction_summary_projects_runner_metrics():
    provider = CountingBundleProvider("tests/fixtures")
    prediction_service = NankanPredictionService(
        nankan_service=NankanService(provider=provider),
        pattern_service=NankankeibaPatternService(provider=NankankeibaPatternFixtureProvider("tests/fixtures")),
    )

    summary = await prediction_service.get_prediction_summary(
        date(2026, 7, 6),
        "kawasaki",
        1,
        4,
        1,
    )

    assert summary.race_id == "2026070621040101"
    assert summary.trend.race_count_completed >= 0
    assert summary.leading_jockeys.period == "recent_3months"
    assert len(summary.runners) >= 1
    assert summary.runners[0].win_odds is not None
    assert summary.runners[0].best_time is not None
    assert summary.runners[0].closing_speed is not None
    assert summary.runners[0].pattern is not None
    assert summary.runners[0].pattern.course_rate is not None
    assert summary.runners[0].pattern.jockey_trainer_course_rate is not None


@pytest.mark.asyncio
async def test_nankankeiba_pattern_bundle_fetches_categories_concurrently():
    provider = ConcurrentPatternProvider("tests/fixtures")
    service = NankankeibaPatternService(provider=provider)

    bundle = await service.get_pattern_bundle(date(2026, 7, 6), "kawasaki", 4, 1, 1)

    assert bundle.categories == ["pattern_kis", "pattern_uma", "pattern_cho", "pattern_kis_cho"]
    assert len(bundle.runners) == 7
    assert provider.max_active_calls > 1


def _unpublished_weight_card_html() -> str:
    return """
    <html><body>
      <h1>1R 川崎 ダ1400m 発走時刻 15:00 天候:晴 馬場:ダ良</h1>
      <p>Ｃ３(一)(二)</p>
      <table>
        <tr><th>枠</th><th>馬</th><th>馬名</th><th>性齢</th><th>単勝</th><th>馬体重</th><th>斤量</th><th>騎手</th><th></th><th>調教師</th><th></th></tr>
        <tr><td>1</td><td>1</td><td>テストホースA</td><td>牡4</td><td>2.1</td><td></td><td>56.0</td><td>町田直希</td><td></td><td>テスト厩舎</td><td></td></tr>
        <tr><td>2</td><td>2</td><td>テストホースB</td><td>牝5</td><td>4.8</td><td></td><td>54.0</td><td>野畑凌</td><td></td><td>テスト厩舎</td><td></td></tr>
      </table>
    </body></html>
    """
