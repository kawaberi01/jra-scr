from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import time
from urllib.parse import urlencode

import httpx

from .errors import UpstreamServiceError


NAR_NETKEIBA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


class NarNetkeibaProviderError(UpstreamServiceError):
    pass


@dataclass(frozen=True)
class NarNetkeibaPageContent:
    source: str
    content: str


class BaseNarNetkeibaProvider:
    async def fetch_calendar(self, year: int, month: int, jyo_cd: str | None = None) -> NarNetkeibaPageContent:
        raise NotImplementedError

    async def fetch_race_list(self, kaisai_date: str, kaisai_id: str) -> NarNetkeibaPageContent:
        raise NotImplementedError

    async def fetch_race_card(self, race_id: str) -> NarNetkeibaPageContent:
        raise NotImplementedError

    async def fetch_race_result(self, race_id: str) -> NarNetkeibaPageContent:
        raise NotImplementedError

    async def fetch_odds(self, race_id: str, odds_type: str) -> NarNetkeibaPageContent:
        raise NotImplementedError


class NarNetkeibaHttpProvider(BaseNarNetkeibaProvider):
    def __init__(
        self,
        base_url: str = "https://nar.netkeiba.com",
        timeout: float = 10.0,
        retries: int = 2,
        backoff_seconds: float = 0.5,
        min_interval_seconds: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.min_interval_seconds = min_interval_seconds
        self._throttle_lock = asyncio.Lock()
        self._last_request_started_at = 0.0

    async def fetch_calendar(self, year: int, month: int, jyo_cd: str | None = None) -> NarNetkeibaPageContent:
        params = {"year": str(year), "month": str(month)}
        if jyo_cd:
            params["jyo_cd"] = jyo_cd
        return await self._get("/top/calendar.html", params)

    async def fetch_race_list(self, kaisai_date: str, kaisai_id: str) -> NarNetkeibaPageContent:
        return await self._get(
            "/top/race_list_sub.html",
            {
                "kaisai_date": kaisai_date,
                "kaisai_id": kaisai_id,
                "rf": "race_list",
            },
        )

    async def fetch_race_card(self, race_id: str) -> NarNetkeibaPageContent:
        return await self._get("/race/shutuba.html", {"race_id": race_id})

    async def fetch_race_result(self, race_id: str) -> NarNetkeibaPageContent:
        return await self._get("/race/result.html", {"race_id": race_id, "rf": "race_list"})

    async def fetch_odds(self, race_id: str, odds_type: str) -> NarNetkeibaPageContent:
        return await self._get("/odds/", {"race_id": race_id, "type": odds_type})

    async def _get(self, path: str, params: dict[str, str]) -> NarNetkeibaPageContent:
        url = f"{self.base_url}{path}?{urlencode(params)}"
        response = await self._request_with_retry(url)
        return NarNetkeibaPageContent(source=str(response.url), content=self._decode_content(response))

    async def _request_with_retry(self, url: str) -> httpx.Response:
        last_error: NarNetkeibaProviderError | None = None
        for attempt in range(self.retries + 1):
            try:
                await self._wait_for_min_interval()
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    response = await client.get(url, headers=NAR_NETKEIBA_HEADERS)
            except httpx.TimeoutException as exc:
                last_error = NarNetkeibaProviderError(f"failed to fetch {url}: timeout")
                if attempt == self.retries:
                    raise last_error from exc
            except httpx.RequestError as exc:
                last_error = NarNetkeibaProviderError(f"failed to fetch {url}: {exc.__class__.__name__}")
                if attempt == self.retries:
                    raise last_error from exc
            else:
                if response.status_code < 400:
                    return response
                last_error = NarNetkeibaProviderError(f"failed to fetch {url}: HTTP {response.status_code}")
                if response.status_code < 500 or attempt == self.retries:
                    raise last_error
            await asyncio.sleep(self.backoff_seconds * (2**attempt))
        assert last_error is not None
        raise last_error

    async def _wait_for_min_interval(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        async with self._throttle_lock:
            now = time.monotonic()
            wait_seconds = self._last_request_started_at + self.min_interval_seconds - now
            if wait_seconds > 0:
                await asyncio.sleep(wait_seconds)
            self._last_request_started_at = time.monotonic()

    @staticmethod
    def _decode_content(response: httpx.Response) -> str:
        for encoding in (response.encoding, "utf-8", "euc_jp", "shift_jis"):
            if not encoding:
                continue
            try:
                return response.content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return response.content.decode("utf-8", errors="ignore")


class NarNetkeibaFixtureProvider(BaseNarNetkeibaProvider):
    def __init__(self, fixture_dir: str | Path) -> None:
        self.fixture_dir = Path(fixture_dir)

    async def fetch_calendar(self, year: int, month: int, jyo_cd: str | None = None) -> NarNetkeibaPageContent:
        suffix = f"_jyo{jyo_cd}" if jyo_cd else ""
        return self._load(f"nar_calendar_{year}{month:02d}{suffix}.html")

    async def fetch_race_list(self, kaisai_date: str, kaisai_id: str) -> NarNetkeibaPageContent:
        return self._load(f"nar_race_list_sub_{kaisai_id}.html")

    async def fetch_race_card(self, race_id: str) -> NarNetkeibaPageContent:
        return self._load(f"nar_race_card_{race_id}.html")

    async def fetch_race_result(self, race_id: str) -> NarNetkeibaPageContent:
        return self._load(f"nar_race_result_{race_id}.html")

    async def fetch_odds(self, race_id: str, odds_type: str) -> NarNetkeibaPageContent:
        return self._load(f"nar_odds_{odds_type}_{race_id}.html")

    def _load(self, name: str) -> NarNetkeibaPageContent:
        path = self.fixture_dir / name
        if not path.exists():
            raise NarNetkeibaProviderError(f"fixture not found: {path}")
        content = path.read_bytes()
        for encoding in ("utf-8", "euc_jp", "shift_jis"):
            try:
                return NarNetkeibaPageContent(source=str(path), content=content.decode(encoding))
            except UnicodeDecodeError:
                continue
        return NarNetkeibaPageContent(source=str(path), content=content.decode("utf-8", errors="ignore"))
