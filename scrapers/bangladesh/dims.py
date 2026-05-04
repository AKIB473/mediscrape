"""DIMS scraper - dimsbd.com - 28k+ brands, 2228 generics, FDA pregnancy categories.

Research findings (2026-05):
  - dimsbd.com drug brand/price data is BEHIND A PAYWALL (DIMS Premium subscription)
  - Free web access shows: generic names list only (no brands, prices, clinical info)
  - The website requires a modern browser (JS-rendered, blocks 'outdated browser' UAs)
  - Generic names ARE visible without login via /generics/{letter} pages

Strategy:
  - Use Playwright to render /generics/{letter} pages (bypasses browser-check)
  - Extract all generic drug names visible on the listing
  - For each generic, try to scrape the individual generic page for whatever is free
  - Any clinical data found is a bonus; most detail is behind paywall
  - Mark data source accurately so users know to expect limited fields
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator

from models.drug import Drug
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)

_SITE_BASE = "https://www.dimsbd.com"
_LETTERS = ["numeric"] + list("abcdefghijklmnopqrstuvwxyz")


class DIMSScraper(BaseScrapingScraper):
    name = "dims"
    base_url = _SITE_BASE
    rate_limit = 0.5
    use_stealth = False  # Playwright handles this directly

    async def scrape_all(self) -> AsyncIterator[Drug]:
        try:
            from playwright.async_api import async_playwright
            _playwright_available = True
        except ImportError:
            _playwright_available = False
            logger.warning("DIMS: playwright not installed; no data will be collected")

        if not _playwright_available:
            return

        from playwright.async_api import async_playwright as _apw
        async with _apw() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            for letter in _LETTERS:
                try:
                    generics = await self._get_generics_for_letter(page, letter)
                    logger.info(f"DIMS: letter={letter!r} → {len(generics)} generics")
                    for name in generics:
                        yield Drug(
                            source="dims",
                            source_url=f"{_SITE_BASE}/generics/{letter}",
                            generic_name=name,
                            extra={
                                "dims_note": "Generic name only; brand/price data requires DIMS Premium subscription",
                                "letter_page": letter,
                            },
                        )
                    await asyncio.sleep(self.rate_limit)
                except Exception as e:
                    logger.warning(f"DIMS: error on letter {letter!r}: {e}")

            await browser.close()

    async def _get_generics_for_letter(self, page, letter: str) -> list[str]:
        """Load /generics/{letter} and extract all visible generic names."""
        await page.goto(f"{_SITE_BASE}/generics/{letter}", wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(1000)

        # Get page text
        text = await page.evaluate("document.body.innerText")
        lines = text.splitlines()

        generics: list[str] = []
        for line in lines:
            line = line.strip()
            # Skip nav/footer/promo text
            if not line:
                continue
            if any(
                skip in line.lower()
                for skip in (
                    "dims", "premium", "buy now", "get it now", "generics", "indications",
                    "brands", "companies", "my account", "home", "privacy", "copyright",
                    "contact", "all rights", "reserved", "#", "a-z", "sign in", "register",
                    "brand & generic", "brand &amp;",
                )
            ):
                continue
            # Generic drug names: start with capital letter, reasonable length
            if re.match(r"^[A-Z][A-Za-z0-9 +&'/-]{2,80}$", line):
                generics.append(line)

        return generics
