from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import httpx


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class PageContent:
    source: str
    content: str


class BaseProvider:
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


class HttpProvider(BaseProvider):
    def __init__(self, base_url: str = "https://www.jra.jp", timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

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

    async def post_jradb(self, path: str, cname: str) -> PageContent:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.post(url, data={"cname": cname})
        if response.status_code >= 400:
            raise ProviderError(f"failed to fetch {url}: HTTP {response.status_code}")
        return PageContent(source=url, content=response.text)

    async def fetch_jradb(self, path: str, cname: str) -> PageContent:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url, params={"CNAME": cname})
        if response.status_code >= 400:
            raise ProviderError(f"failed to fetch {url}: HTTP {response.status_code}")
        return PageContent(source=str(response.url), content=response.text)

    async def _get(self, path: str) -> PageContent:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url)
        if response.status_code >= 400:
            raise ProviderError(f"failed to fetch {url}: HTTP {response.status_code}")
        return PageContent(source=url, content=response.text)


class FixtureProvider(BaseProvider):
    def __init__(self, fixture_dir: str | Path) -> None:
        self.fixture_dir = Path(fixture_dir)

    async def fetch_races(self, target_date: date, course: str | None = None) -> PageContent:
        suffix = f"_{course}" if course else ""
        name = f"races_{target_date.isoformat()}{suffix}.html"
        return self._load(name)

    async def fetch_race_card(self, race_id: str) -> PageContent:
        return self._load(f"race_card_{race_id}.html")

    async def fetch_race_odds(self, race_id: str) -> PageContent:
        return self._load(f"race_odds_{race_id}.html")

    async def fetch_race_result(self, race_id: str) -> PageContent:
        return self._load(f"race_result_{race_id}.html")

    async def post_jradb(self, path: str, cname: str) -> PageContent:
        if path.endswith("accessD.html") and cname == "pw01dli00/F3":
            return self._load("jradb_accessD_select.html")
        if path.endswith("accessD.html") and cname == "pw01drl00062026020820260322/83":
            return self._load("jradb_accessD_meeting_nakayama_20260322.html")
        if path.endswith("accessO.html") and cname == "pw151ouS306202602081120260322Z/95":
            return self._load("jradb_accessO_race_202603220611.html")
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
