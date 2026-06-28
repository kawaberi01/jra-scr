import asyncio
import logging

import httpx
import pytest

from jra_srb.provider import HttpProvider, ProviderError


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


class SequencedAsyncClient:
    def __init__(self, responses: list[httpx.Response | Exception]):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, params=None):
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def post(self, url, data=None):
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_http_provider_defaults_to_jra_go_jp():
    provider = HttpProvider()
    assert provider.base_url == "https://www.jra.go.jp"


def test_http_provider_accepts_access_control_settings():
    provider = HttpProvider(max_concurrency=1, min_interval_seconds=0.25)

    assert provider.max_concurrency == 1
    assert provider.min_interval_seconds == 0.25


@pytest.mark.asyncio
async def test_provider_logs_successful_request(monkeypatch, caplog):
    response = httpx.Response(
        200,
        content="ok".encode("shift_jis"),
        request=httpx.Request("GET", "https://www.jra.go.jp/JRADB/accessD.html?CNAME=test"),
    )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: DummyAsyncClient(response))

    provider = HttpProvider()
    with caplog.at_level(logging.INFO, logger="jra_srb.provider"):
        await provider.fetch_jradb("/JRADB/accessD.html", "test")

    assert any(record.message == "provider_request_succeeded" for record in caplog.records)


@pytest.mark.asyncio
async def test_provider_respects_min_interval_between_requests(monkeypatch):
    response = httpx.Response(
        200,
        content="ok".encode("shift_jis"),
        request=httpx.Request("GET", "https://www.jra.go.jp/JRADB/accessD.html?CNAME=test"),
    )
    sleeps: list[float] = []

    async def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: DummyAsyncClient(response))
    monkeypatch.setattr(asyncio, "sleep", record_sleep)

    provider = HttpProvider(min_interval_seconds=1.0, backoff_seconds=0)
    await provider.fetch_jradb("/JRADB/accessD.html", "test")
    await provider.fetch_jradb("/JRADB/accessD.html", "test")

    assert sleeps
    assert sleeps[0] > 0


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


@pytest.mark.asyncio
async def test_fetch_jradb_retries_timeout_then_succeeds(monkeypatch):
    response = httpx.Response(
        200,
        content="3回中山1日".encode("shift_jis"),
        headers={"Content-Type": "text/html"},
        request=httpx.Request("GET", "https://www.jra.go.jp/JRADB/accessD.html?CNAME=test"),
    )
    attempts: list[httpx.Response | Exception] = [
        httpx.ReadTimeout("timed out", request=httpx.Request("GET", "https://www.jra.go.jp/JRADB/accessD.html")),
        response,
    ]

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: SequencedAsyncClient(attempts))

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    provider = HttpProvider(retries=1, backoff_seconds=0)
    page = await provider.fetch_jradb("/JRADB/accessD.html", "test")

    assert page.content == "3回中山1日"
    assert attempts == []


@pytest.mark.asyncio
async def test_post_jradb_retries_http_503_then_succeeds(monkeypatch):
    error_response = httpx.Response(
        503,
        content=b"",
        request=httpx.Request("POST", "https://www.jra.go.jp/JRADB/accessO.html"),
    )
    success_response = httpx.Response(
        200,
        content="ok".encode("shift_jis"),
        request=httpx.Request("POST", "https://www.jra.go.jp/JRADB/accessO.html"),
    )
    attempts: list[httpx.Response | Exception] = [error_response, success_response]

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: SequencedAsyncClient(attempts))

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    provider = HttpProvider(retries=1, backoff_seconds=0)
    page = await provider.post_jradb("/JRADB/accessO.html", "test")

    assert page.source == "https://www.jra.go.jp/JRADB/accessO.html"
    assert page.content == "ok"
    assert attempts == []


@pytest.mark.asyncio
async def test_fetch_jradb_does_not_retry_http_404(monkeypatch):
    not_found_response = httpx.Response(
        404,
        content=b"",
        request=httpx.Request("GET", "https://www.jra.go.jp/JRADB/accessD.html?CNAME=test"),
    )
    attempts: list[httpx.Response | Exception] = [not_found_response]

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: SequencedAsyncClient(attempts))

    async def no_sleep(_: float) -> None:
        raise AssertionError("sleep should not be called for non-retryable responses")

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    provider = HttpProvider(retries=3, backoff_seconds=0)

    with pytest.raises(ProviderError, match="HTTP 404"):
        await provider.fetch_jradb("/JRADB/accessD.html", "test")

    assert attempts == []
