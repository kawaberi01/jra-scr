from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import time
from urllib.parse import urlencode

import httpx

from .errors import UpstreamServiceError


NETKEIBA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


class NetkeibaProviderError(UpstreamServiceError):
    pass


@dataclass(frozen=True)
class NetkeibaPageContent:
    source: str
    content: str


class BaseNetkeibaProvider:
    async def fetch_race_result(self, race_id: str) -> NetkeibaPageContent:
        raise NotImplementedError

    async def fetch_odds_view(self, race_id: str) -> NetkeibaPageContent:
        raise NotImplementedError

    async def fetch_odds_api(self, race_id: str) -> NetkeibaPageContent:
        raise NotImplementedError


class NetkeibaHttpProvider(BaseNetkeibaProvider):
    def __init__(
        self,
        base_url: str = "https://race.sp.netkeiba.com/",
        timeout: float = 10.0,
        retries: int = 2,
        backoff_seconds: float = 0.5,
        min_interval_seconds: float = 1.0,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.min_interval_seconds = min_interval_seconds
        self._throttle_lock = asyncio.Lock()
        self._last_request_started_at = 0.0

    async def fetch_race_result(self, race_id: str) -> NetkeibaPageContent:
        return await self._get(
            {
                "pid": "race_result",
                "race_id": race_id,
                "rf": "race_toggle_menu",
            }
        )

    async def fetch_odds_view(self, race_id: str) -> NetkeibaPageContent:
        return await self._get(
            {
                "pid": "odds_view",
                "race_id": race_id,
                "rf": "race_toggle_menu",
            }
        )

    async def fetch_odds_api(self, race_id: str) -> NetkeibaPageContent:
        return await self._get(
            {
                "pid": "api_get_jra_odds",
                "input": "UTF-8",
                "output": "json",
                "type": "all",
                "action": "init",
                "race_id": race_id,
                "sort": "ninki",
                "compress": "0",
            }
        )

    async def _get(self, params: dict[str, str]) -> NetkeibaPageContent:
        url = f"{self.base_url}?{urlencode(params)}"
        response = await self._request_with_retry(url)
        return NetkeibaPageContent(source=str(response.url), content=self._decode_content(response))

    async def _request_with_retry(self, url: str) -> httpx.Response:
        last_error: NetkeibaProviderError | None = None
        for attempt in range(self.retries + 1):
            try:
                await self._wait_for_min_interval()
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    response = await client.get(url, headers=NETKEIBA_HEADERS)
            except httpx.TimeoutException as exc:
                last_error = NetkeibaProviderError(f"failed to fetch {url}: timeout")
                if attempt == self.retries:
                    raise last_error from exc
            except httpx.RequestError as exc:
                last_error = NetkeibaProviderError(f"failed to fetch {url}: {exc.__class__.__name__}")
                if attempt == self.retries:
                    raise last_error from exc
            else:
                if response.status_code < 400:
                    return response
                last_error = NetkeibaProviderError(f"failed to fetch {url}: HTTP {response.status_code}")
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


class NetkeibaFixtureProvider(BaseNetkeibaProvider):
    def __init__(self, fixture_dir: str | Path) -> None:
        self.fixture_dir = Path(fixture_dir)

    async def fetch_race_result(self, race_id: str) -> NetkeibaPageContent:
        return self._load(f"netkeiba_race_result_{race_id}.html")

    async def fetch_odds_view(self, race_id: str) -> NetkeibaPageContent:
        return self._load(f"netkeiba_odds_view_{race_id}.html")

    async def fetch_odds_api(self, race_id: str) -> NetkeibaPageContent:
        return self._load(f"netkeiba_odds_api_{race_id}.json")

    def _load(self, name: str) -> NetkeibaPageContent:
        path = self.fixture_dir / name
        if not path.exists():
            raise NetkeibaProviderError(f"fixture not found: {path}")
        content = path.read_bytes()
        for encoding in ("utf-8", "euc_jp", "shift_jis"):
            try:
                return NetkeibaPageContent(source=str(path), content=content.decode(encoding))
            except UnicodeDecodeError:
                continue
        return NetkeibaPageContent(source=str(path), content=content.decode("utf-8", errors="ignore"))
