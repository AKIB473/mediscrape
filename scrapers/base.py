from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import AsyncIterator

import httpx
import orjson
from scrapling import Fetcher, StealthyFetcher, DynamicFetcher
from scrapling.parser import Selector
from scrapling.engines.toolbelt.custom import Response as ScraplingResponse
from tenacity import retry, stop_after_attempt, wait_exponential

from models.drug import Drug, ScrapeMeta
from utils.bypass import (
    BypassSession,
    fetch_bypass,
    get_headers,
    _curl_available,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Patch scrapling classes to add css_first() for convenience           #
# ------------------------------------------------------------------ #

def _css_first(self, selector):
    results = self.css(selector)
    if results:
        return results.first if hasattr(results, 'first') else results[0]
    return None

if not hasattr(Selector, 'css_first'):
    Selector.css_first = _css_first
if not hasattr(ScraplingResponse, 'css_first'):
    ScraplingResponse.css_first = _css_first


# ------------------------------------------------------------------ #
# Minimal HTML response shim so bypass HTML strings work like          #
# scrapling Response objects (css/text access)                         #
# ------------------------------------------------------------------ #

class _HTMLPage:
    """Thin wrapper around raw HTML string with .css() and .text support."""

    def __init__(self, html: str, url: str = ""):
        self._html = html
        self.url = url
        self._soup = None

    @property
    def text(self) -> str:
        return self._html

    def _get_soup(self):
        if self._soup is None:
            from lxml import html as lxml_html
            self._soup = lxml_html.fromstring(self._html)
        return self._soup

    def css(self, selector: str):
        """Return list of _Element wrappers."""
        try:
            from lxml import html as lxml_html
            from lxml.cssselect import CSSSelector
            root = self._get_soup()
            sel = CSSSelector(selector)
            return [_Elem(e) for e in sel(root)]
        except Exception:
            return []

    def css_first(self, selector: str):
        results = self.css(selector)
        return results[0] if results else None

    @property
    def status(self) -> int:
        return 200


class _Elem:
    """Thin lxml element wrapper compatible with scrapling API."""

    def __init__(self, elem):
        self._elem = elem

    @property
    def text(self) -> str:
        from lxml import etree
        return (etree.tostring(self._elem, method="text", encoding="unicode") or "").strip()

    @property
    def tag(self) -> str:
        t = self._elem.tag
        return t if isinstance(t, str) else ""

    @property
    def attrib(self) -> dict:
        return dict(self._elem.attrib)

    @property
    def parent(self):
        p = self._elem.getparent()
        return _Elem(p) if p is not None else None

    def css(self, selector: str):
        try:
            from lxml.cssselect import CSSSelector
            sel = CSSSelector(selector)
            return [_Elem(e) for e in sel(self._elem)]
        except Exception:
            return []

    def css_first(self, selector: str):
        results = self.css(selector)
        return results[0] if results else None


# ------------------------------------------------------------------ #
# Base scraper classes                                                  #
# ------------------------------------------------------------------ #

class BaseScraper(ABC):
    """Base class for all drug scrapers."""

    name: str = "base"
    base_url: str = ""
    rate_limit: float = 1.0  # seconds between requests

    def __init__(self, data_dir: Path = Path("data")):
        self.data_dir = data_dir / self.name
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._last_request = 0.0

    async def throttle(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.rate_limit:
            await asyncio.sleep(self.rate_limit - elapsed)
        self._last_request = time.time()

    @abstractmethod
    async def scrape_all(self) -> AsyncIterator[Drug]:
        """Yield all drugs from this source."""
        ...

    async def run(self) -> ScrapeMeta:
        """Run the scraper and save results."""
        start = time.time()
        meta = ScrapeMeta(source=self.name)
        drugs: list[Drug] = []
        scrape_failed = False

        try:
            async for drug in self.scrape_all():
                drugs.append(drug)
                meta.total_drugs += 1
                if meta.total_drugs % 100 == 0:
                    logger.info(f"[{self.name}] Scraped {meta.total_drugs} drugs...")
        except Exception as e:
            logger.error(f"[{self.name}] Error during scraping: {e}")
            meta.errors += 1
            scrape_failed = True
        finally:
            await self._cleanup_resources()

        meta.duration_seconds = time.time() - start

        output_file = self.data_dir / "drugs.json"
        old_checksum = self._file_checksum(output_file)
        if scrape_failed and not drugs:
            meta.checksum = old_checksum
            if old_checksum:
                logger.warning(
                    f"[{self.name}] Scrape failed with no data; preserving existing drugs.json"
                )
            else:
                logger.warning(
                    f"[{self.name}] Scrape failed with no data; skipping drugs.json write"
                )
        else:
            data = [orjson.loads(d.to_json_bytes()) for d in drugs]
            output_file.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))
            new_checksum = self._file_checksum(output_file)
            meta.checksum = new_checksum
            if old_checksum and old_checksum != new_checksum:
                logger.info(f"[{self.name}] Data changed! Old: {old_checksum[:8]}, New: {new_checksum[:8]}")

        meta_file = self.data_dir / "meta.json"
        meta_file.write_bytes(orjson.dumps(meta.model_dump(mode="json"), option=orjson.OPT_INDENT_2))
        logger.info(f"[{self.name}] Done: {meta.total_drugs} drugs in {meta.duration_seconds:.1f}s")
        return meta

    async def _cleanup_resources(self):
        await self._close_resource(getattr(self, "client", None), "client")
        await self._close_resource(getattr(self, "fetcher", None), "fetcher")
        sess = getattr(self, "_bypass_session", None)
        if sess is not None:
            try:
                await sess.__aexit__(None, None, None)
            except Exception:
                pass

    async def _close_resource(self, resource, label: str):
        if resource is None:
            return
        close_fn = getattr(resource, "aclose", None)
        if not callable(close_fn):
            close_fn = getattr(resource, "close", None)
        if not callable(close_fn):
            return
        try:
            result = close_fn()
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            logger.debug(f"[{self.name}] Failed to close {label}: {e}", exc_info=True)

    @staticmethod
    def _file_checksum(path: Path) -> str | None:
        if not path.exists():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def css_first(page, selector: str):
        """Get first element matching CSS selector (compat with scrapling)."""
        results = page.css(selector)
        if results:
            return results.first if hasattr(results, 'first') else results[0]
        return None

    def extract_jsonld(self, page) -> list[dict]:
        """Extract JSON-LD structured data from a page."""
        # Works with both scrapling Response and _HTMLPage
        try:
            scripts = page.css('script[type="application/ld+json"]')
        except Exception:
            return []
        results = []
        for script in scripts:
            try:
                text = script.text if hasattr(script, "text") else ""
                if text:
                    data = orjson.loads(text)
                    if isinstance(data, list):
                        results.extend(data)
                    else:
                        results.append(data)
            except Exception:
                continue
        return results


class BaseScrapingScraper(BaseScraper):
    """
    Scraper using scrapling for HTML scraping.

    Anti-bot bypass stack (applied automatically when use_bypass=True):
      1. curl_cffi TLS impersonation  — Cloudflare Bot Management
      2. cloudscraper                 — older CF challenges
      3. Playwright (headless Chrome) — JS challenges, heavy protection
      4. scrapling StealthyFetcher    — last resort
    """

    use_stealth: bool = False
    use_dynamic: bool = False
    use_bypass: bool = True   # Enable progressive bypass by default

    def __init__(self, data_dir: Path = Path("data")):
        super().__init__(data_dir)
        if self.use_dynamic:
            self.fetcher = DynamicFetcher()
        elif self.use_stealth:
            self.fetcher = StealthyFetcher()
        else:
            self.fetcher = Fetcher()
        self._is_stealth = self.use_stealth or self.use_dynamic
        self._bypass_session: BypassSession | None = None

    async def _get_bypass_session(self) -> BypassSession:
        """Lazily create and open a BypassSession for this scraper."""
        if self._bypass_session is None:
            self._bypass_session = BypassSession(
                self.base_url,
                rate_limit=self.rate_limit,
                use_playwright=self.use_dynamic,
            )
            await self._bypass_session.__aenter__()
        return self._bypass_session

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
    async def fetch_page(self, url: str, **kwargs):
        """
        Fetch a page using the best available bypass method.

        Strategy:
          - If use_bypass=True (default): try curl_cffi → cloudscraper → scrapling
          - Returns an object with .css(), .css_first(), .text, .status
        """
        await self.throttle()
        logger.debug(f"[{self.name}] Fetching: {url}")

        if self.use_bypass:
            # Try bypass methods first
            session = await self._get_bypass_session()
            html = await session.get(url)
            if html and len(html) > 200:
                return _HTMLPage(html, url)

            # curl session failed → try one-shot Playwright fetch
            if self.use_dynamic or self.use_stealth:
                from utils.bypass import _fetch_playwright
                html = await _fetch_playwright(url)
                if html and len(html) > 200:
                    return _HTMLPage(html, url)

        # Scrapling fallback
        if self._is_stealth:
            response = self.fetcher.fetch(url, **kwargs)
        else:
            response = self.fetcher.get(url, **kwargs)

        if response.status != 200:
            raise httpx.HTTPStatusError(
                f"HTTP {response.status}",
                request=None,
                response=None,
            )
        return response

    async def fetch_html(self, url: str) -> str | None:
        """Return raw HTML string using bypass stack."""
        page = await self.fetch_page(url)
        if hasattr(page, "text"):
            return page.text
        return None


class BaseAPIScraper(BaseScraper):
    """Scraper using httpx for REST API access, with curl_cffi fallback."""

    headers: dict = {}
    timeout: float = 30.0

    def __init__(self, data_dir: Path = Path("data")):
        super().__init__(data_dir)
        # Prefer curl_cffi for API requests too (better TLS fingerprint)
        if _curl_available:
            from curl_cffi.requests import AsyncSession as CurlAsync
            import random
            self._curl_session = CurlAsync(impersonate="chrome124")
            self._use_curl = True
        else:
            self._use_curl = False
        self.client = httpx.AsyncClient(
            headers={**get_headers(), **self.headers},
            timeout=self.timeout,
            follow_redirects=True,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
    async def api_get(self, url: str, params: dict | None = None) -> dict:
        await self.throttle()
        logger.debug(f"[{self.name}] API GET: {url}")
        if self._use_curl:
            try:
                r = await self._curl_session.get(
                    url, params=params, headers=self.headers, timeout=self.timeout
                )
                r.raise_for_status()
                return r.json()
            except Exception:
                pass
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
    async def api_get_text(self, url: str, params: dict | None = None) -> str:
        await self.throttle()
        if self._use_curl:
            try:
                r = await self._curl_session.get(
                    url, params=params, headers=self.headers, timeout=self.timeout
                )
                r.raise_for_status()
                return r.text
            except Exception:
                pass
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.text

    async def _cleanup_resources(self):
        await super()._cleanup_resources()
        if self._use_curl:
            try:
                await self._curl_session.__aexit__(None, None, None)
            except Exception:
                pass

    async def __aenter__(self):
        if self._use_curl:
            await self._curl_session.__aenter__()
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()
        if self._use_curl:
            try:
                await self._curl_session.__aexit__(*args)
            except Exception:
                pass
