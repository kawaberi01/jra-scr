# JRA Data Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JRA 公式サイトの `JRADB + cname` 導線を辿って、開催地単位・単レース単位でレース一覧、出馬表、券種単位オッズ、結果・払戻を取得できる FastAPI 基盤を完成させる。

**Architecture:** 既存の `provider` / `service` / `app` / `extractors` 構成を維持しつつ、JRA 固有のナビゲーションを `navigation` に分離する。オンライン系は短 TTL キャッシュを使い、過去結果は別バッチ入口を持たせる。オッズは `race_id + bet_type` を取得単位にし、必要なら組み合わせフィルタで絞り込む。

**Tech Stack:** Python 3.12, FastAPI, httpx, BeautifulSoup4, pytest, pytest-asyncio

---

## File Structure

### 既存ファイルの役割

- `src/jra_srb/provider.py`
  - 現在の HTML 取得責務
  - 今回は単純な `/races` 直アクセスから、JRA ナビゲーション利用に差し替える
- `src/jra_srb/service.py`
  - キャッシュとユースケースの中心
  - 今回は開催地単位 API と券種単位オッズ API を追加する
- `src/jra_srb/app.py`
  - FastAPI 入口
  - 今回は `meetings` 系の URL とオッズ用クエリを追加する
- `src/jra_srb/extractors.py`
  - HTML から構造化データへ変換
  - 今回は開催選択・レース一覧・オッズ組み合わせの抽出を追加する
- `src/jra_srb/models.py`
  - Pydantic モデル
  - 今回は開催地単位レスポンス、オッズ券種レスポンス、組み合わせフィルタ結果を追加する
- `tests/test_service.py`
  - サービス層のユースケーステスト
- `tests/test_api.py`
  - FastAPI エンドポイントテスト
- `tests/fixtures/*`
  - 取得 HTML フィクスチャ

### 新規作成するファイル

- `src/jra_srb/navigation.py`
  - `JRADB + cname` 遷移の解決責務
- `tests/test_navigation.py`
  - 開催選択、開催リンク、レースリンクの解決テスト
- `tests/fixtures/jradb_accessD_select.html`
  - 出馬表の開催選択ページ
- `tests/fixtures/jradb_accessO_select.html`
  - オッズの開催選択ページ
- `tests/fixtures/jradb_accessS_select.html`
  - レース結果の開催選択ページ
- `tests/fixtures/jradb_accessD_meeting_*.html`
  - 開催選択後の出馬表ページ
- `tests/fixtures/jradb_accessO_bettype_*.html`
  - 券種単位のオッズページ

### 変更の原則

- JRA 固有の遷移知識は `navigation.py` に閉じ込める
- HTML の抽出は `extractors.py`
- キャッシュやユースケースは `service.py`
- HTTP 入口は `app.py`
- 過去結果バッチは最後に小さく追加する

## Task 1: JRA Navigation Layer

**Files:**
- Create: `src/jra_srb/navigation.py`
- Modify: `src/jra_srb/provider.py`
- Modify: `src/jra_srb/extractors.py`
- Test: `tests/test_navigation.py`
- Create: `tests/fixtures/jradb_accessD_select.html`
- Create: `tests/fixtures/jradb_accessO_select.html`
- Create: `tests/fixtures/jradb_accessS_select.html`

- [ ] **Step 1: Write the failing tests for navigation parsing**

```python
from datetime import date

from jra_srb.navigation import JraNavigation
from jra_srb.provider import PageContent


async def test_find_meeting_link_for_course_and_date():
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


async def test_find_result_meeting_link_for_course_and_date():
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
```

- [ ] **Step 2: Run the navigation tests to confirm failure**

Run: `pytest tests/test_navigation.py -v`
Expected: FAIL because `jra_srb.navigation` does not exist yet.

- [ ] **Step 3: Implement minimal navigation model and parser**

```python
from dataclasses import dataclass
from datetime import date
import re

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class ResolvedTransition:
    label: str
    cname: str


class JraNavigation:
    def resolve_meeting_from_selection(self, page, target_date: date, course: str, kind: str):
        soup = BeautifulSoup(page.content, "html.parser")
        links = soup.select("a[onclick*='doAction']")
        prefix = {"card": "pw01drl", "odds": "pw15orl", "result": "pw01srl"}[kind]
        course_name = {"nakayama": "中山", "hanshin": "阪神"}[course]
        target_day = target_date.strftime("%Y%m%d")

        for link in links:
            onclick = link.get("onclick", "")
            text = link.get_text(" ", strip=True)
            match = re.search(r"'([^']+)'", onclick)
            if not match:
                continue
            cname = match.group(1)
            if prefix in cname and course_name in text and target_day in cname:
                return ResolvedTransition(label=text, cname=cname)
        raise LookupError(f"meeting not found: {course} {target_date} {kind}")
```

- [ ] **Step 4: Update provider to support JRA POST navigation**

```python
async def post_jradb(self, path: str, cname: str) -> PageContent:
    url = f"{self.base_url}{path}"
    async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
        response = await client.post(url, data={"cname": cname})
    if response.status_code >= 400:
        raise ProviderError(f"failed to fetch {url}: HTTP {response.status_code}")
    return PageContent(source=url, content=response.text)
```

- [ ] **Step 5: Re-run navigation tests**

Run: `pytest tests/test_navigation.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/jra_srb/navigation.py src/jra_srb/provider.py src/jra_srb/extractors.py tests/test_navigation.py tests/fixtures/jradb_accessD_select.html tests/fixtures/jradb_accessO_select.html tests/fixtures/jradb_accessS_select.html
git commit -m "feat: add JRA navigation layer"
```

If Git is not initialized in this workspace, skip the commit and continue.

## Task 2: Meeting-Level Race Index API

**Files:**
- Modify: `src/jra_srb/models.py`
- Modify: `src/jra_srb/service.py`
- Modify: `src/jra_srb/app.py`
- Modify: `src/jra_srb/extractors.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`
- Create: `tests/fixtures/jradb_accessD_meeting_nakayama_20260322.html`

- [ ] **Step 1: Write the failing service tests for meeting-level race index**

```python
async def test_get_meeting_returns_twelve_races(service):
    meeting = await service.get_meeting(date(2026, 3, 22), "nakayama")

    assert meeting.course == "nakayama"
    assert len(meeting.races) == 12
    assert meeting.races[10].race_no == 11
```

- [ ] **Step 2: Run the service test and confirm failure**

Run: `pytest tests/test_service.py::test_get_meeting_returns_twelve_races -v`
Expected: FAIL because `get_meeting` does not exist.

- [ ] **Step 3: Add focused models**

```python
class MeetingRace(BaseModel):
    race_no: int
    race_id: str
    race_name: str | None = None


class MeetingSnapshot(BaseModel):
    date: date
    course: str
    races: list[MeetingRace]
    source: str
    fetched_at: datetime
```

- [ ] **Step 4: Implement meeting parsing and service method**

```python
async def get_meeting(self, target_date: date, course: str) -> MeetingSnapshot:
    select_page = await self.provider.post_jradb("/JRADB/accessD.html", "pw01dli00/F3")
    resolved = self.navigation.resolve_meeting_from_selection(select_page, target_date, course, "card")
    meeting_page = await self.provider.post_jradb("/JRADB/accessD.html", resolved.cname)
    races = parse_meeting_races(meeting_page.content)
    return MeetingSnapshot(...)
```

- [ ] **Step 5: Add API endpoint**

```python
@app.get("/meetings/{date}/{course}")
async def get_meeting(date: date, course: str, svc: JraService = Depends(get_service)):
    return await svc.get_meeting(date, course)
```

- [ ] **Step 6: Run focused tests**

Run: `pytest tests/test_service.py::test_get_meeting_returns_twelve_races tests/test_api.py -v`
Expected: PASS for the new meeting endpoint tests.

- [ ] **Step 7: Commit**

```bash
git add src/jra_srb/models.py src/jra_srb/service.py src/jra_srb/app.py src/jra_srb/extractors.py tests/test_service.py tests/test_api.py tests/fixtures/jradb_accessD_meeting_nakayama_20260322.html
git commit -m "feat: add meeting-level race index API"
```

If Git is not initialized in this workspace, skip the commit and continue.

## Task 3: Single-Race Card Resolution by Date, Course, Race Number

**Files:**
- Modify: `src/jra_srb/service.py`
- Modify: `src/jra_srb/app.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write the failing tests for race card resolution**

```python
async def test_get_race_card_by_meeting_coordinates(service):
    card = await service.get_race_card_by_number(
        target_date=date(2026, 3, 22),
        course="nakayama",
        race_no=11,
    )

    assert card.race_id
    assert card.race_name
    assert len(card.runners) > 0
```

- [ ] **Step 2: Run the focused test and confirm failure**

Run: `pytest tests/test_service.py::test_get_race_card_by_meeting_coordinates -v`
Expected: FAIL because the method does not exist.

- [ ] **Step 3: Implement race lookup through meeting snapshot**

```python
async def get_race_card_by_number(self, target_date: date, course: str, race_no: int) -> RaceCard:
    meeting = await self.get_meeting(target_date, course)
    race = next(item for item in meeting.races if item.race_no == race_no)
    return await self.get_race_card(race.race_id)
```

- [ ] **Step 4: Add matching FastAPI endpoint**

```python
@app.get("/meetings/{date}/{course}/races/{race_no}/card")
async def get_race_card_by_number(...):
    return await svc.get_race_card_by_number(date, course, race_no)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_service.py::test_get_race_card_by_meeting_coordinates tests/test_api.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/jra_srb/service.py src/jra_srb/app.py tests/test_service.py tests/test_api.py tests/conftest.py
git commit -m "feat: resolve race card by meeting coordinates"
```

If Git is not initialized in this workspace, skip the commit and continue.

## Task 4: Bet-Type Odds Retrieval and Combination Filtering

**Files:**
- Modify: `src/jra_srb/models.py`
- Modify: `src/jra_srb/service.py`
- Modify: `src/jra_srb/app.py`
- Modify: `src/jra_srb/extractors.py`
- Modify: `src/jra_srb/config/parsers/race_odds.json`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`
- Create: `tests/fixtures/jradb_accessO_bettype_trifecta_202603220611.html`

- [ ] **Step 1: Write the failing tests for bet-type odds retrieval**

```python
async def test_get_odds_for_single_bet_type(service):
    odds = await service.get_race_odds("202603220611", bet_type="trifecta")

    assert odds.bet_type == "trifecta"
    assert odds.entries
    assert all(len(item.combination) == 3 for item in odds.entries)


async def test_filter_odds_by_exact_combination(service):
    odds = await service.get_race_odds(
        "202603220611",
        bet_type="trifecta",
        combination=["1", "2", "8"],
    )

    assert len(odds.entries) == 1
    assert odds.entries[0].combination == ["1", "2", "8"]
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `pytest tests/test_service.py -k "bet_type or exact_combination" -v`
Expected: FAIL because the API still returns mixed odds maps.

- [ ] **Step 3: Refactor odds models to be bet-type centric**

```python
class OddsEntry(BaseModel):
    combination: list[str]
    odds: str | None = None
    odds_min: str | None = None
    odds_max: str | None = None
    popularity: str | None = None


class RaceOdds(BaseModel):
    race_id: str
    bet_type: str
    entries: list[OddsEntry]
    fetched_at: datetime
    source: str
    cache_hit: bool = False
```

- [ ] **Step 4: Implement filtering in service**

```python
async def get_race_odds(self, race_id: str, bet_type: str, combination: list[str] | None = None, refresh: bool = False) -> RaceOdds:
    cache_key = f"odds:{race_id}:{bet_type}"
    if not refresh:
        cached = self.cache.get(cache_key)
        if cached is not None:
            return self._filter_odds(cached, combination, cache_hit=True)
    page = await self.provider.fetch_race_odds(race_id, bet_type=bet_type)
    parsed = parse_race_odds(page.content, load_parser_config("race_odds"), bet_type=bet_type)
    result = RaceOdds(...)
    self.cache.set(cache_key, result, ttl_seconds=30)
    return self._filter_odds(result, combination)
```

- [ ] **Step 5: Add endpoint query parameters**

```python
@app.get("/races/{race_id}/odds")
async def get_race_odds(race_id: str, bet_type: str, combination: str | None = None, refresh: bool = False, svc: JraService = Depends(get_service)):
    parsed_combination = combination.split(",") if combination else None
    return await svc.get_race_odds(race_id, bet_type=bet_type, combination=parsed_combination, refresh=refresh)
```

- [ ] **Step 6: Run focused odds tests**

Run: `pytest tests/test_service.py tests/test_api.py -k "odds" -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/jra_srb/models.py src/jra_srb/service.py src/jra_srb/app.py src/jra_srb/extractors.py src/jra_srb/config/parsers/race_odds.json tests/test_service.py tests/test_api.py tests/fixtures/jradb_accessO_bettype_trifecta_202603220611.html
git commit -m "feat: add bet-type odds retrieval and filtering"
```

If Git is not initialized in this workspace, skip the commit and continue.

## Task 5: Meeting-Coordinate Odds Endpoint

**Files:**
- Modify: `src/jra_srb/service.py`
- Modify: `src/jra_srb/app.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests for odds by course/date/race number**

```python
async def test_get_odds_by_meeting_coordinates(service):
    odds = await service.get_race_odds_by_number(
        target_date=date(2026, 3, 22),
        course="nakayama",
        race_no=11,
        bet_type="trifecta",
    )

    assert odds.bet_type == "trifecta"
    assert odds.entries
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `pytest tests/test_service.py::test_get_odds_by_meeting_coordinates -v`
Expected: FAIL because the method does not exist.

- [ ] **Step 3: Implement race-id resolution through the meeting snapshot**

```python
async def get_race_odds_by_number(self, target_date: date, course: str, race_no: int, bet_type: str, combination: list[str] | None = None, refresh: bool = False) -> RaceOdds:
    meeting = await self.get_meeting(target_date, course)
    race = next(item for item in meeting.races if item.race_no == race_no)
    return await self.get_race_odds(race.race_id, bet_type=bet_type, combination=combination, refresh=refresh)
```

- [ ] **Step 4: Add the matching endpoint**

```python
@app.get("/meetings/{date}/{course}/races/{race_no}/odds")
async def get_race_odds_by_number(...):
    return await svc.get_race_odds_by_number(...)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_service.py tests/test_api.py -k "meeting_coordinates or odds_by_number" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/jra_srb/service.py src/jra_srb/app.py tests/test_service.py tests/test_api.py
git commit -m "feat: add meeting-coordinate odds endpoint"
```

If Git is not initialized in this workspace, skip the commit and continue.

## Task 6: Results and Payouts by Meeting Coordinates

**Files:**
- Modify: `src/jra_srb/service.py`
- Modify: `src/jra_srb/app.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`
- Create: `tests/fixtures/jradb_accessS_meeting_nakayama_20260322.html`

- [ ] **Step 1: Write the failing tests for results by meeting coordinates**

```python
async def test_get_result_by_meeting_coordinates(service):
    result = await service.get_race_result_by_number(
        target_date=date(2026, 3, 22),
        course="nakayama",
        race_no=11,
    )

    assert result.race_name
    assert result.results
    assert result.payouts
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `pytest tests/test_service.py::test_get_result_by_meeting_coordinates -v`
Expected: FAIL because the method does not exist.

- [ ] **Step 3: Implement result lookup through meeting resolution**

```python
async def get_race_result_by_number(self, target_date: date, course: str, race_no: int) -> RaceResult:
    meeting = await self.get_meeting(target_date, course)
    race = next(item for item in meeting.races if item.race_no == race_no)
    return await self.get_race_result(race.race_id)
```

- [ ] **Step 4: Add the result endpoint**

```python
@app.get("/meetings/{date}/{course}/races/{race_no}/result")
async def get_race_result_by_number(...):
    return await svc.get_race_result_by_number(date, course, race_no)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_service.py tests/test_api.py -k "result_by_meeting_coordinates" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/jra_srb/service.py src/jra_srb/app.py tests/test_service.py tests/test_api.py tests/fixtures/jradb_accessS_meeting_nakayama_20260322.html
git commit -m "feat: add meeting-coordinate result endpoint"
```

If Git is not initialized in this workspace, skip the commit and continue.

## Task 7: Past Result Batch Collector Skeleton

**Files:**
- Create: `src/jra_srb/batch.py`
- Modify: `src/jra_srb/service.py`
- Modify: `tests/test_service.py`
- Create: `tests/test_batch.py`

- [ ] **Step 1: Write the failing tests for batch collection**

```python
async def test_collect_results_range_calls_service_for_each_day(fake_service):
    collector = PastResultCollector(service=fake_service)

    await collector.collect(date(2026, 3, 21), date(2026, 3, 22), ["nakayama", "hanshin"])

    assert fake_service.calls == [
        (date(2026, 3, 21), "nakayama"),
        (date(2026, 3, 21), "hanshin"),
        (date(2026, 3, 22), "nakayama"),
        (date(2026, 3, 22), "hanshin"),
    ]
```

- [ ] **Step 2: Run the batch test and confirm failure**

Run: `pytest tests/test_batch.py -v`
Expected: FAIL because `PastResultCollector` does not exist.

- [ ] **Step 3: Implement a minimal collector skeleton**

```python
class PastResultCollector:
    def __init__(self, service: JraService):
        self.service = service

    async def collect(self, from_date: date, to_date: date, courses: list[str]) -> None:
        current = from_date
        while current <= to_date:
            for course in courses:
                await self.service.get_meeting(current, course)
            current += timedelta(days=1)
```

- [ ] **Step 4: Add TODO markers for persistence**

```python
# TODO: Persist collected results/payouts to a pluggable storage backend.
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_batch.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/jra_srb/batch.py src/jra_srb/service.py tests/test_batch.py tests/test_service.py
git commit -m "feat: add past result batch collector skeleton"
```

If Git is not initialized in this workspace, skip the commit and continue.

## Task 8: End-to-End Verification and Docs Refresh

**Files:**
- Modify: `README.md`
- Modify: `tests/test_api.py`
- Modify: `docs/superpowers/specs/2026-03-22-jra-data-retrieval-design.md` if implementation diverged

- [ ] **Step 1: Add or update API usage examples in README**

```md
GET /meetings/2026-03-22/nakayama
GET /meetings/2026-03-22/nakayama/races/11/card
GET /meetings/2026-03-22/nakayama/races/11/odds?bet_type=trifecta&combination=1,2,8&refresh=true
GET /meetings/2026-03-22/nakayama/races/11/result
```

- [ ] **Step 2: Run the full test suite**

Run: `pytest -v`
Expected: PASS

- [ ] **Step 3: Run a local smoke test**

Run: `uv run uvicorn jra_srb.app:app --reload`
Expected: Server starts without import errors.

- [ ] **Step 4: Manually verify representative endpoints**

Run:

```bash
curl 'http://127.0.0.1:8000/meetings/2026-03-22/nakayama'
curl 'http://127.0.0.1:8000/meetings/2026-03-22/nakayama/races/11/odds?bet_type=trifecta&combination=1,2,8&refresh=true'
```

Expected: JSON responses with stable schema.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_api.py docs/superpowers/specs/2026-03-22-jra-data-retrieval-design.md
git commit -m "docs: update usage examples for JRA retrieval API"
```

If Git is not initialized in this workspace, skip the commit and finish.

## Notes for the Implementer

- Keep `cname` internal. Never expose it from the API contract.
- Do not broaden the scope to odds history persistence in this phase.
- Prefer adding focused fixtures over hitting the live site in tests.
- Preserve the current provider/service/app separation instead of rewriting the codebase around Scrapy or browser automation.
- If JRA pages require additional hidden form fields later, extend `navigation.py` instead of scattering that logic across services.
