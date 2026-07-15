from pathlib import Path

import httpx

from web_to_api.investigator import BrowserObservation, SiteInvestigator
from web_to_api.models import SourceStrategy
from web_to_api.settings import Settings
from web_to_api.storage import ProjectStore


class FakeBrowser:
    def __init__(self) -> None:
        self.calls = 0

    async def inspect(self, url: str) -> BrowserObservation:
        self.calls += 1
        return BrowserObservation(
            final_url=url,
            html="<html><body><main><article>Rendered</article></main></body></html>",
            network_requests=[
                {
                    "event_type": "request",
                    "url": "https://93.184.216.34/api/matches?token=secret",
                    "resource_type": "xhr",
                    "content_type": "application/json",
                }
            ],
        )


async def test_investigation_discovers_sources_redacts_urls_and_caches(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(
            200,
            text=(
                "<html><head><title>Sport</title>"
                '<link rel="alternate" type="application/rss+xml" href="/feed.xml">'
                '<script type="application/ld+json">{"@type":"SportsEvent"}</script>'
                "</head><body><main><article>Match</article></main></body></html>"
            ),
            headers={"content-type": "text/html; charset=utf-8"},
        )

    settings = Settings(data_dir=tmp_path, cache_ttl_seconds=3600)
    store = ProjectStore(settings)
    browser = FakeBrowser()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    investigator = SiteInvestigator(settings, store, browser=browser, client=client)
    try:
        first = await investigator.investigate("https://93.184.216.34/")
        second = await investigator.investigate("https://93.184.216.34/")
    finally:
        await client.aclose()
        await store.close()

    assert first.title == "Sport"
    assert first.preferred_candidate is not None
    assert first.preferred_candidate.strategy is SourceStrategy.RSS
    assert second.cached is True
    assert calls == 2  # robots.txt and the document, only on the first investigation
    assert browser.calls == 1
    backend = next(
        item for item in first.candidates if item.strategy is SourceStrategy.BACKEND_JSON
    )
    assert "secret" not in backend.url
    assert "REDACTED" in backend.url
