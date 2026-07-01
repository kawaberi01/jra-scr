from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
import logging
from pathlib import Path
import time
from urllib.parse import urlencode

import httpx

from .errors import UpstreamServiceError

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
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


class ProviderError(UpstreamServiceError):
    pass


@dataclass(frozen=True)
class PageContent:
    source: str
    content: str


class BaseProvider:
    async def check_upstream(self) -> PageContent:
        raise NotImplementedError

    async def fetch_jradb(self, path: str, cname: str) -> PageContent:
        raise NotImplementedError

    async def post_jradb(self, path: str, cname: str) -> PageContent:
        raise NotImplementedError

    async def fetch_races(self, target_date: date, course: str | None = None) -> PageContent:
        raise NotImplementedError

    async def fetch_race_card(self, race_id: str) -> PageContent:
        raise NotImplementedError

    async def fetch_race_odds(self, race_id: str) -> PageContent:
        raise NotImplementedError

    async def fetch_race_result(self, race_id: str) -> PageContent:
        raise NotImplementedError

    async def fetch_calendar_month(self, year: int, month: int) -> PageContent:
        raise NotImplementedError


class HttpProvider(BaseProvider):
    def __init__(
        self,
        base_url: str = "https://www.jra.go.jp",
        timeout: float = 10.0,
        retries: int = 2,
        backoff_seconds: float = 0.5,
        max_concurrency: int = 5,
        min_interval_seconds: float = 0.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.max_concurrency = max_concurrency
        self.min_interval_seconds = min_interval_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._throttle_lock = asyncio.Lock()
        self._last_request_started_at = 0.0

    async def fetch_races(self, target_date: date, course: str | None = None) -> PageContent:
        params = {"date": target_date.isoformat()}
        if course:
            params["course"] = course
        path = f"/races?{urlencode(params)}"
        return await self._get(path)

    async def fetch_race_card(self, race_id: str) -> PageContent:
        return await self._get(f"/race/{race_id}/card")

    async def fetch_race_odds(self, race_id: str) -> PageContent:
        return await self._get(f"/race/{race_id}/odds")

    async def fetch_race_result(self, race_id: str) -> PageContent:
        return await self._get(f"/race/{race_id}/result")

    async def fetch_calendar_month(self, year: int, month: int) -> PageContent:
        return await self._get(f"/keiba/common/calendar/json/{year}{month:02d}.json")

    async def post_jradb(self, path: str, cname: str) -> PageContent:
        url = f"{self.base_url}{path}"
        content = await self._curl_post_form(url, {"cname": cname})
        return PageContent(source=url, content=content)

    async def fetch_jradb(self, path: str, cname: str) -> PageContent:
        url = f"{self.base_url}{path}"
        response = await self._request_with_retry("get", url, params={"CNAME": cname})
        return PageContent(source=str(response.url), content=self._decode_jra_content(response))

    async def _get(self, path: str) -> PageContent:
        url = f"{self.base_url}{path}"
        try:
            response = await self._request_with_retry("get", url)
            return PageContent(source=url, content=response.text)
        except ProviderError as exc:
            if "HTTP 403" not in str(exc):
                raise
            logger.info("provider_httpx_fallback_to_curl", extra={"url": url})
            content = await self._curl_get(url)
            return PageContent(source=url, content=content)

    async def check_upstream(self) -> PageContent:
        url = f"{self.base_url}/"
        response = await self._request_with_retry("get", url)
        return PageContent(source=str(response.url), content="ok")

    async def _request_with_retry(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_error: ProviderError | None = None
        for attempt in range(self.retries + 1):
            try:
                async with self._semaphore:
                    await self._wait_for_min_interval()
                    headers = {**DEFAULT_HEADERS, **kwargs.pop("headers", {})}
                    async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                        response = await getattr(client, method)(url, headers=headers, **kwargs)
            except httpx.TimeoutException as exc:
                last_error = ProviderError(f"failed to fetch {url}: timeout")
                logger.warning(
                    "provider_request_failed",
                    extra={"method": method, "url": url, "attempt": attempt + 1, "error": "timeout"},
                )
                if attempt == self.retries:
                    raise last_error from exc
            except httpx.RequestError as exc:
                last_error = ProviderError(f"failed to fetch {url}: {exc.__class__.__name__}")
                logger.warning(
                    "provider_request_failed",
                    extra={"method": method, "url": url, "attempt": attempt + 1, "error": exc.__class__.__name__},
                )
                if attempt == self.retries:
                    raise last_error from exc
            else:
                if response.status_code < 400:
                    logger.info(
                        "provider_request_succeeded",
                        extra={
                            "method": method,
                            "url": str(response.url),
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                        },
                    )
                    return response
                last_error = ProviderError(f"failed to fetch {url}: HTTP {response.status_code}")
                logger.warning(
                    "provider_request_failed",
                    extra={
                        "method": method,
                        "url": str(response.url),
                        "status_code": response.status_code,
                        "attempt": attempt + 1,
                    },
                )
                if not self._should_retry_status(response.status_code) or attempt == self.retries:
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
    def _should_retry_status(status_code: int) -> bool:
        return status_code >= 500

    @staticmethod
    def _decode_jra_content(response: httpx.Response) -> str:
        return response.content.decode("shift_jis", errors="ignore")

    async def _curl_get(self, url: str) -> str:
        return await self._run_curl(["-L", "-A", DEFAULT_HEADERS["User-Agent"], "--silent", "--show-error", url], url)

    async def _curl_post_form(self, url: str, data: dict[str, str]) -> str:
        args = ["-L", "-A", DEFAULT_HEADERS["User-Agent"], "--silent", "--show-error"]
        for key, value in data.items():
            args.extend(["-d", f"{key}={value}"])
        args.append(url)
        return await self._run_curl(args, url)

    async def _run_curl(self, args: list[str], url: str) -> str:
        process = await asyncio.create_subprocess_exec(
            "curl.exe",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="ignore").strip() or f"curl exit {process.returncode}"
            raise ProviderError(f"failed to fetch {url}: {detail}")
        encoding = self._sniff_encoding(url, stdout)
        return stdout.decode(encoding, errors="ignore")

    @staticmethod
    def _sniff_encoding(url: str, content: bytes) -> str:
        if url.endswith(".json"):
            return "utf-8"
        head = content[:512].lower()
        if b"charset=shift_jis" in head or b"charset=\"shift_jis\"" in head:
            return "shift_jis"
        return "utf-8"


class FixtureProvider(BaseProvider):
    def __init__(self, fixture_dir: str | Path) -> None:
        self.fixture_dir = Path(fixture_dir)

    async def fetch_races(self, target_date: date, course: str | None = None) -> PageContent:
        suffix = f"_{course}" if course else ""
        name = f"races_{target_date.isoformat()}{suffix}.html"
        return self._load(name)

    async def check_upstream(self) -> PageContent:
        return PageContent(source=str(self.fixture_dir), content="ok")

    async def fetch_race_card(self, race_id: str) -> PageContent:
        return self._load(f"race_card_{race_id}.html")

    async def fetch_race_odds(self, race_id: str) -> PageContent:
        return self._load(f"race_odds_{race_id}.html")

    async def fetch_race_result(self, race_id: str) -> PageContent:
        primary = self.fixture_dir / f"race_result_{race_id}.html"
        if primary.exists():
            return self._load(primary.name)
        fallback = self.fixture_dir / f"jradb_accessS_race_{race_id}.html"
        if fallback.exists():
            return self._load(fallback.name)
        return self._load(primary.name)

    async def fetch_calendar_month(self, year: int, month: int) -> PageContent:
        return self._load(f"calendar_{year}{month:02d}.json")

    async def post_jradb(self, path: str, cname: str) -> PageContent:
        if path.endswith("accessD.html") and cname == "pw01dli00/F3":
            return self._load("jradb_accessD_select.html")
        if path.endswith("accessD.html") and cname == "pw01drl00062026020820260322/83":
            return self._load("jradb_accessD_meeting_nakayama_20260322.html")
        if path.endswith("accessO.html") and cname == "pw151ouS306202602081120260322Z/95":
            return self._load("jradb_accessO_race_202603220611.html")
        if path.endswith("accessO.html") and cname == "pw154ouS306202602081120260322Z/21":
            return self._load("jradb_accessO_quinella_202603220611.html")
        if path.endswith("accessO.html") and cname == "pw155ouS306202602081120260322Z/A5":
            return self._load("jradb_accessO_wide_202603220611.html")
        if path.endswith("accessO.html") and cname == "pw156ouS306202602081120260322Z/29":
            return self._load("jradb_accessO_exacta_202603220611.html")
        if path.endswith("accessO.html") and cname == "pw157ouS306202602081120260322Z99/0F":
            return self._load("jradb_accessO_trio_202603220611.html")
        if path.endswith("accessO.html") and cname == "pw158ouS306202602081120260322Z/31":
            return self._load("jradb_accessO_trifecta_202603220611.html")
        if path.endswith("accessO.html") and cname == "pw15oli00/6D":
            return self._load("jradb_accessO_select.html")
        if path.endswith("accessS.html") and cname == "pw01sli00/AF":
            return self._load("jradb_accessS_select.html")
        if path.endswith("accessH.html") and cname == "pw01hli00/03":
            return self._load("jradb_accessH_select.html")
        if path.endswith("accessH.html") and cname == "pw01hde01062026020820260322/2B":
            return self._load("jradb_accessH_meeting_nakayama_20260322.html")
        raise ProviderError(f"fixture not found for path={path} cname={cname}")

    async def fetch_jradb(self, path: str, cname: str) -> PageContent:
        if path.endswith("accessD.html") and cname == "pw01dde0106202602081120260322/F2":
            return self._load("jradb_accessD_race_202603220611.html")
        raise ProviderError(f"fixture not found for path={path} cname={cname}")

    def _load(self, name: str) -> PageContent:
        path = self.fixture_dir / name
        if not path.exists():
            raise ProviderError(f"fixture not found: {path}")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="shift_jis", errors="ignore")
        return PageContent(source=str(path), content=content)
