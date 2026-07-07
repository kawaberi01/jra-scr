from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import time

import httpx

from .errors import UpstreamServiceError
from .nankankeiba_pattern_extractors import build_pattern_url_path


NANKANKEIBA_PATTERN_HEADERS = {
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


class NankankeibaPatternProviderError(UpstreamServiceError):
    pass


@dataclass(frozen=True)
class NankankeibaPatternPageContent:
    source: str
    content: str


class BaseNankankeibaPatternProvider:
    async def fetch_pattern(self, race_id: str, category: str) -> NankankeibaPatternPageContent:
        raise NotImplementedError


class NankankeibaPatternHttpProvider(BaseNankankeibaPatternProvider):
    def __init__(
        self,
        base_url: str = "https://www.nankankeiba.com",
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

    async def fetch_pattern(self, race_id: str, category: str) -> NankankeibaPatternPageContent:
        path = build_pattern_url_path(category, race_id)
        url = f"{self.base_url}{path}"
        response = await self._request_with_retry(url)
        return NankankeibaPatternPageContent(source=str(response.url), content=self._decode_content(response))

    async def _request_with_retry(self, url: str) -> httpx.Response:
        last_error: NankankeibaPatternProviderError | None = None
        for attempt in range(self.retries + 1):
            try:
                await self._wait_for_min_interval()
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    response = await client.get(url, headers=NANKANKEIBA_PATTERN_HEADERS)
            except httpx.TimeoutException as exc:
                last_error = NankankeibaPatternProviderError(f"failed to fetch {url}: timeout")
                if attempt == self.retries:
                    raise last_error from exc
            except httpx.RequestError as exc:
                last_error = NankankeibaPatternProviderError(f"failed to fetch {url}: {exc.__class__.__name__}")
                if attempt == self.retries:
                    raise last_error from exc
            else:
                if response.status_code < 400:
                    return response
                last_error = NankankeibaPatternProviderError(f"failed to fetch {url}: HTTP {response.status_code}")
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
        for encoding in (response.encoding, "utf-8", "cp932", "shift_jis"):
            if not encoding:
                continue
            try:
                return response.content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return response.content.decode("utf-8", errors="ignore")


class NankankeibaPatternFixtureProvider(BaseNankankeibaPatternProvider):
    def __init__(self, fixture_dir: str | Path) -> None:
        self.fixture_dir = Path(fixture_dir)

    async def fetch_pattern(self, race_id: str, category: str) -> NankankeibaPatternPageContent:
        return self._load(f"nankankeiba_{category}_{race_id}.html")

    def _load(self, name: str) -> NankankeibaPatternPageContent:
        path = self.fixture_dir / name
        if not path.exists():
            raise NankankeibaPatternProviderError(f"fixture not found: {path}")
        content = path.read_bytes()
        for encoding in ("utf-8", "cp932", "shift_jis"):
            try:
                return NankankeibaPatternPageContent(source=str(path), content=content.decode(encoding))
            except UnicodeDecodeError:
                continue
        return NankankeibaPatternPageContent(source=str(path), content=content.decode("utf-8", errors="ignore"))
