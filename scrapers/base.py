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

logger = logging.getLogger(__name__)

# Patch scrapling classes to add css_first() for convenience
def _css_first(self, selector):
    results = self.css(selector)
    if results:
        return results.first if hasattr(results, 'first') else results[0]
    return None

if not hasattr(Selector, 'css_first'):
    Selector.css_first = _css_first
if not hasattr(ScraplingResponse, 'css_first'):
    ScraplingResponse.css_first = _css_first


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

        # Save drugs. If scraping failed before collecting any records, preserve
        # existing data instead of replacing it with an empty file.
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
            data = [
                orjson.loads(d.to_json_bytes())
                for d in drugs
            ]
            output_file.write_bytes(orjson.dumps(data, option=orjson.OPT_INDENT_2))

            new_checksum = self._file_checksum(output_file)
            meta.checksum = new_checksum

            if old_checksum and old_checksum != new_checksum:
                logger.info(f"[{self.name}] Data changed! Old: {old_checksum[:8]}, New: {new_checksum[:8]}")

        # Save metadata
        meta_file = self.data_dir / "meta.json"
        meta_file.write_bytes(orjson.dumps(meta.model_dump(mode="json"), option=orjson.OPT_INDENT_2))

        logger.info(
            f"[{self.name}] Done: {meta.total_drugs} drugs in {meta.duration_seconds:.1f}s"
        )
        return meta

    async def _cleanup_resources(self):
        await self._close_resource(getattr(self, "client", None), "client")
        await self._close_resource(getattr(self, "fetcher", None), "fetcher")

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
        scripts = page.css('script[type="application/ld+json"]')
        results = []
        for script in scripts:
            try:
                data = orjson.loads(script.text)
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
            except Exception:
                continue
        return results


class BaseScrapingScraper(BaseScraper):
    """Scraper using scrapling for HTML scraping."""

    use_stealth: bool = False
    use_dynamic: bool = False  # For JS-heavy sites (uses real browser)

    def __init__(self, data_dir: Path = Path("data")):
        super().__init__(data_dir)
        if self.use_dynamic:
            self.fetcher = DynamicFetcher()
        elif self.use_stealth:
            self.fetcher = StealthyFetcher()
        else:
            self.fetcher = Fetcher()
        self._is_stealth = self.use_stealth or self.use_dynamic

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
    async def fetch_page(self, url: str, **kwargs):
        await self.throttle()
        logger.debug(f"[{self.name}] Fetching: {url}")
        # StealthyFetcher/DynamicFetcher use .fetch(), Fetcher uses .get()
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


class BaseAPIScraper(BaseScraper):
    """Scraper using httpx for REST API access."""

    headers: dict = {}
    timeout: float = 30.0

    def __init__(self, data_dir: Path = Path("data")):
        super().__init__(data_dir)
        self.client = httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
    async def api_get(self, url: str, params: dict | None = None) -> dict:
        await self.throttle()
        logger.debug(f"[{self.name}] API GET: {url}")
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30))
    async def api_get_text(self, url: str, params: dict | None = None) -> str:
        await self.throttle()
        resp = await self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()
