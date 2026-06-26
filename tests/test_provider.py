import httpx
import pytest

from jra_srb.provider import HttpProvider


class DummyAsyncClient:
    def __init__(self, response: httpx.Response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, params=None):
        return self._response

    async def post(self, url, data=None):
        return self._response


def test_http_provider_defaults_to_jra_go_jp():
    provider = HttpProvider()
    assert provider.base_url == "https://www.jra.go.jp"


@pytest.mark.asyncio
async def test_fetch_jradb_decodes_shift_jis_response(monkeypatch):
    content = "3回中山1日".encode("shift_jis")
    response = httpx.Response(
        200,
        content=content,
        headers={"Content-Type": "text/html"},
        request=httpx.Request("GET", "https://www.jra.go.jp/JRADB/accessD.html?CNAME=test"),
    )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: DummyAsyncClient(response))

    provider = HttpProvider()
    page = await provider.fetch_jradb("/JRADB/accessD.html", "test")

    assert page.source == "https://www.jra.go.jp/JRADB/accessD.html?CNAME=test"
    assert page.content == "3回中山1日"
