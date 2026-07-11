from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import time

import httpx

from .errors import ResourceNotFoundError, UpstreamServiceError
from .prediction_trace import PredictionTraceLogger, get_current_request_trace_id


NANKAN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


NANKAN_BET_TYPE_TO_ODDS_CODE = {
    "win": "01",
    "place": "01",
    "quinella": "04",
    "wide": "04",
    "exacta": "03",
    "trio": "09",
    "trifecta": "08",
}


class NankanProviderError(UpstreamServiceError):
    pass


@dataclass(frozen=True)
class NankanPageContent:
    source: str
    content: str


class BaseNankanProvider:
    async def fetch_calendar(self, year: int, month: int) -> NankanPageContent:
        raise NotImplementedError

    async def fetch_meeting(self, meeting_id: str) -> NankanPageContent:
        raise NotImplementedError

    async def fetch_race_card(self, race_id: str) -> NankanPageContent:
        raise NotImplementedError

    async def fetch_odds(self, race_id: str, bet_type: str) -> NankanPageContent:
        raise NotImplementedError

    async def fetch_result(self, race_id: str) -> NankanPageContent:
        raise NotImplementedError

    async def fetch_trend(self, meeting_id: str, open_date: str) -> NankanPageContent:
        raise NotImplementedError

    async def fetch_best(self, race_id: str, suffix: str) -> NankanPageContent:
        raise NotImplementedError

    async def fetch_horse_profile(self, horse_profile_id: str) -> NankanPageContent:
        raise NotImplementedError

    async def fetch_leading_jockeys(self, condition_code: str) -> NankanPageContent:
        raise NotImplementedError


class NankanHttpProvider(BaseNankanProvider):
    def __init__(
        self,
        base_url: str = "https://www.nankankeiba.com",
        timeout: float = 10.0,
        retries: int = 2,
        backoff_seconds: float = 0.5,
        min_interval_seconds: float = 1.0,
        max_concurrency: int = 3,
        trace_logger: PredictionTraceLogger | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.min_interval_seconds = min_interval_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._throttle_lock = asyncio.Lock()
        self._last_request_started_at = 0.0
        self.trace_logger = trace_logger or PredictionTraceLogger()

    async def fetch_calendar(self, year: int, month: int) -> NankanPageContent:
        return await self._get(f"/calendar/{year:04d}{month:02d}.do")

    async def fetch_meeting(self, meeting_id: str) -> NankanPageContent:
        return await self._get(f"/program/{meeting_id}.do")

    async def fetch_race_card(self, race_id: str) -> NankanPageContent:
        return await self._get(f"/uma_shosai/{race_id}.do")

    async def fetch_odds(self, race_id: str, bet_type: str) -> NankanPageContent:
        odds_code = NANKAN_BET_TYPE_TO_ODDS_CODE[bet_type]
        try:
            return await self._get(f"/odds/{race_id}{odds_code}.do")
        except ResourceNotFoundError as exc:
            raise ResourceNotFoundError(f"nankan odds not available yet: race_id={race_id} bet_type={bet_type}") from exc

    async def fetch_result(self, race_id: str) -> NankanPageContent:
        try:
            return await self._get(f"/result/{race_id}.do")
        except ResourceNotFoundError as exc:
            raise ResourceNotFoundError(f"nankan result not available yet: race_id={race_id}") from exc

    async def fetch_trend(self, meeting_id: str, open_date: str) -> NankanPageContent:
        try:
            return await self._get(f"/race_trend/{meeting_id}.do?open_date={open_date}")
        except ResourceNotFoundError as exc:
            raise ResourceNotFoundError(f"nankan trend not available yet: meeting_id={meeting_id} open_date={open_date}") from exc

    async def fetch_best(self, race_id: str, suffix: str) -> NankanPageContent:
        try:
            return await self._get(f"/best/{race_id}{suffix}.do")
        except ResourceNotFoundError as exc:
            raise ResourceNotFoundError(f"nankan best page not available yet: race_id={race_id} suffix={suffix}") from exc

    async def fetch_horse_profile(self, horse_profile_id: str) -> NankanPageContent:
        try:
            return await self._get(f"/uma_info/{horse_profile_id}.do")
        except ResourceNotFoundError as exc:
            raise ResourceNotFoundError(f"nankan horse profile not available yet: horse_profile_id={horse_profile_id}") from exc

    async def fetch_leading_jockeys(self, condition_code: str) -> NankanPageContent:
        try:
            return await self._get(f"/leading_kis/{condition_code}.do")
        except ResourceNotFoundError as exc:
            raise ResourceNotFoundError(f"nankan leading jockeys not available yet: condition_code={condition_code}") from exc

    async def _get(self, path: str) -> NankanPageContent:
        url = f"{self.base_url}{path}"
        response = await self._request_with_retry(url)
        return NankanPageContent(source=str(response.url), content=self._decode_content(response))

    async def _request_with_retry(self, url: str) -> httpx.Response:
        last_error: NankanProviderError | None = None
        request_trace_id = get_current_request_trace_id()
        for attempt in range(self.retries + 1):
            started_at = time.perf_counter()
            self.trace_logger.write(
                "upstream_request",
                phase="start",
                request_trace_id=request_trace_id,
                provider="nankan",
                url=url,
                attempt=attempt + 1,
            )
            try:
                async with self._semaphore:
                    await self._wait_for_min_interval()
                    async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                        response = await client.get(url, headers=NANKAN_HEADERS)
            except httpx.TimeoutException as exc:
                last_error = NankanProviderError(f"failed to fetch {url}: timeout")
                self.trace_logger.write(
                    "upstream_request",
                    phase="error",
                    request_trace_id=request_trace_id,
                    provider="nankan",
                    url=url,
                    attempt=attempt + 1,
                    elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
                    error_type=exc.__class__.__name__,
                    error="timeout",
                )
                if attempt == self.retries:
                    raise last_error from exc
            except httpx.RequestError as exc:
                last_error = NankanProviderError(f"failed to fetch {url}: {exc.__class__.__name__}")
                self.trace_logger.write(
                    "upstream_request",
                    phase="error",
                    request_trace_id=request_trace_id,
                    provider="nankan",
                    url=url,
                    attempt=attempt + 1,
                    elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
                    error_type=exc.__class__.__name__,
                    error=exc.__class__.__name__,
                )
                if attempt == self.retries:
                    raise last_error from exc
            else:
                if response.status_code < 400:
                    self.trace_logger.write(
                        "upstream_request",
                        phase="done",
                        request_trace_id=request_trace_id,
                        provider="nankan",
                        url=str(response.url),
                        attempt=attempt + 1,
                        elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
                        status_code=response.status_code,
                    )
                    return response
                if response.status_code == 404:
                    self.trace_logger.write(
                        "upstream_request",
                        phase="error",
                        request_trace_id=request_trace_id,
                        provider="nankan",
                        url=str(response.url),
                        attempt=attempt + 1,
                        elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
                        status_code=response.status_code,
                        error_type="ResourceNotFoundError",
                        error="nankan page not found",
                    )
                    raise ResourceNotFoundError(f"nankan page not found: {url}")
                last_error = NankanProviderError(f"failed to fetch {url}: HTTP {response.status_code}")
                self.trace_logger.write(
                    "upstream_request",
                    phase="error",
                    request_trace_id=request_trace_id,
                    provider="nankan",
                    url=str(response.url),
                    attempt=attempt + 1,
                    elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
                    status_code=response.status_code,
                    error_type="NankanProviderError",
                    error=f"HTTP {response.status_code}",
                )
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
        for encoding in ("shift_jis", response.encoding, "utf-8", "euc_jp"):
            if not encoding:
                continue
            try:
                return response.content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return response.content.decode("utf-8", errors="ignore")


class NankanFixtureProvider(BaseNankanProvider):
    def __init__(self, fixture_dir: str | Path) -> None:
        self.fixture_dir = Path(fixture_dir)

    async def fetch_calendar(self, year: int, month: int) -> NankanPageContent:
        return self._load(f"nankan_calendar_{year:04d}{month:02d}.html")

    async def fetch_meeting(self, meeting_id: str) -> NankanPageContent:
        return self._load(f"nankan_program_{meeting_id}.html")

    async def fetch_race_card(self, race_id: str) -> NankanPageContent:
        return self._load(f"nankan_card_{race_id}.html")

    async def fetch_odds(self, race_id: str, bet_type: str) -> NankanPageContent:
        odds_code = NANKAN_BET_TYPE_TO_ODDS_CODE[bet_type]
        return self._load(f"nankan_odds_{race_id}{odds_code}.html")

    async def fetch_result(self, race_id: str) -> NankanPageContent:
        return self._load(f"nankan_result_{race_id}.html")

    async def fetch_trend(self, meeting_id: str, open_date: str) -> NankanPageContent:
        return self._load(f"nankan_trend_{meeting_id}_{open_date}.html")

    async def fetch_best(self, race_id: str, suffix: str) -> NankanPageContent:
        return self._load(f"nankan_best_{race_id}{suffix}.html")

    async def fetch_horse_profile(self, horse_profile_id: str) -> NankanPageContent:
        return self._load(f"nankan_horse_{horse_profile_id}.html")

    async def fetch_leading_jockeys(self, condition_code: str) -> NankanPageContent:
        return self._load(f"nankan_leading_jockeys_{condition_code}.html")

    def _load(self, name: str) -> NankanPageContent:
        path = self.fixture_dir / name
        if not path.exists():
            raise ResourceNotFoundError(f"fixture not found: {path}")
        content = path.read_bytes()
        for encoding in ("utf-8", "shift_jis", "euc_jp"):
            try:
                return NankanPageContent(source=str(path), content=content.decode(encoding))
            except UnicodeDecodeError:
                continue
        return NankanPageContent(source=str(path), content=content.decode("utf-8", errors="ignore"))
