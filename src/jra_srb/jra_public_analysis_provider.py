from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time

import httpx

from .models import JraSourceKeys


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
}


@dataclass(frozen=True)
class JraPublicPage:
    source: str
    url: str
    content: str


class BaseJraPublicAnalysisProvider:
    async def fetch(self, source: str, keys: JraSourceKeys) -> JraPublicPage:
        raise NotImplementedError


class JraPublicAnalysisHttpProvider(BaseJraPublicAnalysisProvider):
    def __init__(self, timeout: float = 10.0, retries: int = 1, min_interval_seconds: float = 10.0) -> None:
        self.timeout = timeout
        self.retries = retries
        self.min_interval_seconds = min_interval_seconds
        self._locks = {source: asyncio.Lock() for source in ("netkeiba", "keibalab", "umanity")}
        self._last_started = {source: 0.0 for source in self._locks}

    async def fetch(self, source: str, keys: JraSourceKeys) -> JraPublicPage:
        url = self._url(source, keys)
        lock = self._locks.get(source)
        if lock is None:
            raise ValueError(f"unsupported public source={source}")
        async with lock:
            wait = self.min_interval_seconds - (time.monotonic() - self._last_started[source])
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_started[source] = time.monotonic()
            last_error: Exception | None = None
            for attempt in range(self.retries + 1):
                try:
                    async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=HEADERS) as client:
                        response = await client.get(url)
                    response.raise_for_status()
                    return JraPublicPage(source=source, url=str(response.url), content=_decode(response))
                except (httpx.HTTPError, UnicodeError) as exc:
                    last_error = exc
                    if attempt < self.retries:
                        await asyncio.sleep(0.5 * (attempt + 1))
            raise RuntimeError(f"failed to fetch public source={source}: {last_error}")

    @staticmethod
    def _url(source: str, keys: JraSourceKeys) -> str:
        if source == "netkeiba":
            return f"https://race.netkeiba.com/race/data_top.html?race_id={keys.netkeiba_race_id}&rf=race_submenu"
        if source == "keibalab":
            return f"https://www.keibalab.jp/db/race/{keys.keibalab_race_code}/umabashira.html"
        if source == "umanity":
            return f"https://umanity.jp/racedata/race_8.php?code={keys.umanity_race_code}"
        raise ValueError(f"unsupported public source={source}")


def _decode(response: httpx.Response) -> str:
    if response.encoding:
        return response.text
    for encoding in ("utf-8", "cp932", "shift_jis"):
        try:
            return response.content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return response.content.decode("utf-8", errors="replace")
