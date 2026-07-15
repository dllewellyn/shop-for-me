from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import extruct
import feedparser
import httpx
import logfire
from selectolax.parser import HTMLParser

from .models import InvestigationReport, SourceCandidate, SourceStrategy
from .security import assert_robots_allowed, fetch_public, validate_public_url
from .settings import Settings
from .storage import ProjectStore

INVESTIGATOR_VERSION = "1"


@dataclass(slots=True)
class BrowserObservation:
    final_url: str
    html: str
    network_requests: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BrowserInvestigator(Protocol):
    async def inspect(self, url: str) -> BrowserObservation: ...


class Crawl4AIBrowser:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def inspect(self, url: str) -> BrowserObservation:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

        crawler = AsyncWebCrawler(
            config=BrowserConfig(
                headless=True,
                user_agent=self.settings.user_agent,
                verbose=False,
            )
        )

        async def filter_private_requests(page: Any, context: Any, **_: Any) -> Any:
            async def route_filter(route: Any) -> None:
                try:
                    await validate_public_url(route.request.url)
                except (ValueError, OSError):
                    await route.abort()
                else:
                    await route.continue_()

            await context.route("**", route_filter)
            return page

        crawler.crawler_strategy.set_hook("on_page_context_created", filter_private_requests)
        config = CrawlerRunConfig(
            capture_network_requests=True,
            capture_console_messages=False,
            page_timeout=int(self.settings.http_timeout_seconds * 1000),
            wait_for="body",
            scan_full_page=False,
        )
        async with crawler:
            result = await crawler.arun(url=url, config=config)
        if not result.success:
            return BrowserObservation(
                final_url=url,
                html="",
                warnings=[
                    f"Headless investigation failed: {result.error_message or 'unknown error'}"
                ],
            )
        return BrowserObservation(
            final_url=result.url or url,
            html=(result.html or "")[: self.settings.max_response_bytes],
            network_requests=result.network_requests or [],
        )


class SiteInvestigator:
    def __init__(
        self,
        settings: Settings,
        store: ProjectStore,
        *,
        browser: BrowserInvestigator | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        self.store = store
        self.browser = browser or Crawl4AIBrowser(settings)
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.user_agent, "Accept": "*/*"},
        )

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def investigate(self, url: str, *, force_refresh: bool = False) -> InvestigationReport:
        requested = await validate_public_url(url)
        canonical = requested.copy_with(fragment=None)
        cache_key = f"investigation:{INVESTIGATOR_VERSION}:{canonical}"
        if not force_refresh:
            cached = await self.store.cache_get(cache_key)
            if cached:
                return cached.model_copy(update={"cached": True})

        with logfire.span("investigate website", url=str(canonical)):
            await assert_robots_allowed(
                self.client,
                str(canonical),
                user_agent=self.settings.user_agent,
                max_bytes=self.settings.max_response_bytes,
            )
            fetched = await fetch_public(
                self.client,
                str(canonical),
                max_bytes=self.settings.max_response_bytes,
            )
            final_url = str(fetched.response.url)
            content_type = fetched.response.headers.get("content-type", "").split(";", 1)[0]
            text = fetched.body.decode(fetched.response.encoding or "utf-8", errors="replace")
            candidates, title = _inspect_static(final_url, content_type, fetched.body, text)

            observation = await self.browser.inspect(final_url)
            candidates.extend(_inspect_browser(observation, static_html=text))
            candidates = _deduplicate(candidates)
            project_id = _project_id(final_url)
            report = InvestigationReport(
                project_id=project_id,
                requested_url=str(requested),
                canonical_url=observation.final_url or final_url,
                title=title,
                candidates=candidates,
                warnings=observation.warnings,
            )
            await self.store.save_investigation(report)
            await self.store.cache_set(cache_key, report)
            return report


def _inspect_static(
    url: str,
    content_type: str,
    body: bytes,
    text: str,
) -> tuple[list[SourceCandidate], str | None]:
    candidates: list[SourceCandidate] = []
    parsed_feed = feedparser.parse(body)
    if parsed_feed.version and parsed_feed.entries:
        strategy = SourceStrategy.JSON_FEED if "json" in content_type else SourceStrategy.RSS
        candidates.append(
            SourceCandidate(
                strategy=strategy,
                url=url,
                content_type=content_type,
                evidence=(
                    f"The response parsed as {parsed_feed.version} "
                    f"with {len(parsed_feed.entries)} entries"
                ),
                sample_keys=sorted(parsed_feed.entries[0].keys())[:20],
                confidence=0.98,
            )
        )
        return candidates, parsed_feed.feed.get("title")

    if "json" in content_type:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            keys = sorted(value.keys())[:20] if isinstance(value, dict) else []
            candidates.append(
                SourceCandidate(
                    strategy=SourceStrategy.BACKEND_JSON,
                    url=url,
                    content_type=content_type,
                    evidence="The requested URL returns JSON directly",
                    sample_keys=keys,
                    confidence=0.95,
                )
            )
            return candidates, None

    tree = HTMLParser(text)
    title_node = tree.css_first("title")
    title = title_node.text(strip=True) if title_node else None
    for node in tree.css("link[rel~=alternate]"):
        media_type = (node.attributes.get("type") or "").lower()
        href = node.attributes.get("href")
        if not href or not any(token in media_type for token in ("rss", "atom", "feed+json")):
            continue
        strategy = SourceStrategy.JSON_FEED if "feed+json" in media_type else SourceStrategy.RSS
        candidates.append(
            SourceCandidate(
                strategy=strategy,
                url=urljoin(url, href),
                content_type=media_type,
                evidence="Discovered in a rel=alternate feed link",
                confidence=0.9,
            )
        )

    try:
        embedded = extruct.extract(text, base_url=url, syntaxes=["json-ld", "microdata"])
    except (ValueError, TypeError):
        embedded = {}
    for syntax, values in embedded.items():
        if values:
            first = values[0] if isinstance(values, list) else values
            keys = sorted(first.keys())[:20] if isinstance(first, dict) else []
            candidates.append(
                SourceCandidate(
                    strategy=SourceStrategy.EMBEDDED_JSON,
                    url=url,
                    content_type=syntax,
                    evidence=(
                        f"Found {len(values) if isinstance(values, list) else 1} {syntax} records"
                    ),
                    sample_keys=keys,
                    confidence=0.8,
                )
            )

    selectors = _representative_selectors(tree)
    if tree.body is not None:
        candidates.append(
            SourceCandidate(
                strategy=SourceStrategy.STATIC_HTML,
                url=url,
                content_type=content_type,
                evidence="The initial HTML response contains a document body",
                selectors=selectors,
                confidence=0.55 if selectors else 0.35,
            )
        )
    return candidates, title


def _inspect_browser(
    observation: BrowserObservation,
    *,
    static_html: str,
) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    for event in observation.network_requests:
        if event.get("event_type") not in {"request", "response"}:
            continue
        event_url = event.get("url")
        if not event_url:
            continue
        content_type = str(event.get("content_type") or event.get("mime_type") or "")
        resource_type = str(event.get("resource_type") or "")
        if "json" not in content_type.lower() and resource_type not in {"xhr", "fetch"}:
            continue
        candidates.append(
            SourceCandidate(
                strategy=SourceStrategy.BACKEND_JSON,
                url=_redact_url(event_url),
                content_type=content_type or None,
                evidence=f"Observed a browser {resource_type or 'network'} request",
                confidence=0.75,
            )
        )
    if observation.html and len(observation.html) > len(static_html) * 1.15:
        rendered_tree = HTMLParser(observation.html)
        candidates.append(
            SourceCandidate(
                strategy=SourceStrategy.HEADLESS_BROWSER,
                url=observation.final_url,
                content_type="text/html",
                evidence=(
                    "Rendered HTML contains substantially more content than the static response"
                ),
                selectors=_representative_selectors(rendered_tree),
                confidence=0.6,
            )
        )
    return candidates


def _representative_selectors(tree: HTMLParser) -> list[str]:
    selectors: list[str] = []
    for selector in ("main", "article", "table", "ul", "ol", "[class*=match]", "[class*=item]"):
        if tree.css_first(selector):
            selectors.append(selector)
    return selectors[:8]


def _redact_url(url: str) -> str:
    parts = urlsplit(url)
    redacted_query = urlencode(
        [(key, "REDACTED") for key, _ in parse_qsl(parts.query, keep_blank_values=True)]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, redacted_query, ""))


def _project_id(url: str) -> str:
    host = (urlsplit(url).hostname or "site").lower().replace(".", "-")[:32].strip("-")
    digest = hashlib.sha256(url.encode()).hexdigest()[:10]
    return f"{host or 'site'}-{digest}"


def _deduplicate(candidates: list[SourceCandidate]) -> list[SourceCandidate]:
    unique: dict[tuple[SourceStrategy, str], SourceCandidate] = {}
    for candidate in candidates:
        key = (candidate.strategy, candidate.url)
        current = unique.get(key)
        if current is None or candidate.confidence > current.confidence:
            unique[key] = candidate
    return sorted(
        unique.values(),
        key=lambda candidate: (
            {
                "rss": 0,
                "json_feed": 0,
                "backend_json": 1,
                "embedded_json": 2,
                "static_html": 3,
                "headless_browser": 4,
            }[candidate.strategy],
            -candidate.confidence,
        ),
    )
