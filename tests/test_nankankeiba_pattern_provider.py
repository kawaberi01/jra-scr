import pytest

from jra_srb.nankankeiba_pattern_provider import NankankeibaPatternFixtureProvider, NankankeibaPatternHttpProvider


@pytest.mark.asyncio
async def test_fixture_provider_reads_cp932_html():
    provider = NankankeibaPatternFixtureProvider("tests/fixtures")

    page = await provider.fetch_pattern("202607062104010101", "pattern_kis")

    assert page.source.endswith("nankankeiba_pattern_kis_202607062104010101.html")
    assert "勝ちパターン分析" in page.content


@pytest.mark.asyncio
async def test_http_provider_builds_pattern_url_without_request(monkeypatch):
    provider = NankankeibaPatternHttpProvider(base_url="https://example.test")
    captured = {}

    async def fake_request(url: str):
        captured["url"] = url

        class Response:
            encoding = "utf-8"
            content = b"<html></html>"

        response = Response()
        response.url = url
        return response

    monkeypatch.setattr(provider, "_request_with_retry", fake_request)

    await provider.fetch_pattern("202607062104010101", "pattern_uma")

    assert captured["url"] == "https://example.test/pattern_uma/202607062104010101.do"
