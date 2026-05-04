"""BD Medex scraper - bdmedex.com - 35k+ brands, herbal + veterinary included.

Architecture (verified 2026-05):
  bdmedex.com is a React SPA — all drug data loaded client-side via API.
  The page shell renders immediately but drug content requires JS execution.

  Discovery: drug list pages are static HTML with links (CSS-selectable).
  Individual drug pages: must use Playwright to wait for JS render.
  After render, data appears as text in the DOM.

  Page structure after JS render:
    H1 = brand name
    .drug-info or similar = generic, strength, form, manufacturer
    Sections: Indications, Pharmacology, Side Effects, Dosage etc.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator

import httpx
from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

_SKIP_PREFIXES = ["/brand/list-", "/generic/list-", "/company/", "/news/"]
_LETTERS = ["9"] + list("abcdefghijklmnopqrstuvwxyz")

# Known dosage forms
_FORMS = [
    "extended release tablet", "sustained release tablet", "film coated tablet",
    "chewable tablet", "dispersible tablet", "sublingual tablet",
    "powder for suspension", "powder for injection",
    "oral solution", "oral suspension",
    "eye drop", "ear drop", "nasal spray",
    "hard capsule", "soft capsule",
    "tablet", "capsule", "syrup", "suspension", "solution", "injection",
    "cream", "ointment", "gel", "lotion", "suppository", "patch",
    "inhaler", "spray", "drops", "powder", "granules",
    "infusion", "emulsion",
]


class BDMedExScraper(BaseScrapingScraper):
    name = "bdmedex"
    base_url = "https://bdmedex.com"
    rate_limit = 1.0
    use_stealth = True

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Step 1: Collect drug page URLs from listing pages (static HTML)
        urls = await self._collect_urls()
        logger.info(f"BDMedEx: found {len(urls)} drug page URLs")

        # Step 2: Scrape each drug page via Playwright (JS render required)
        for url in urls:
            try:
                drug = await self._scrape_with_playwright(url)
                if drug:
                    yield drug
                else:
                    # Try bypass fallback
                    drug = await self._scrape_page(url)
                    if drug:
                        yield drug
            except Exception as e:
                logger.warning(f"BDMedEx: error {url}: {e}")
            await asyncio.sleep(self.rate_limit)

    async def _collect_urls(self) -> list[str]:
        """Collect all brand and generic page URLs from listing pages."""
        urls: dict[str, None] = {}

        async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True, timeout=15) as client:
            for letter in _LETTERS:
                for path_type in ["brand", "generic"]:
                    try:
                        r = await client.get(f"{self.base_url}/{path_type}/list-{letter}/")
                        if r.status_code != 200:
                            continue
                        html = r.text
                        # Extract links to individual drug pages
                        links = re.findall(
                            rf'href="(/{path_type}/[^/"]+/)"', html
                        )
                        for href in links:
                            if not any(href.startswith(p) for p in _SKIP_PREFIXES):
                                urls[f"{self.base_url}{href}"] = None
                    except Exception:
                        pass
                await asyncio.sleep(0.2)

        return list(urls.keys())

    async def _scrape_with_playwright(self, url: str) -> Drug | None:
        """Scrape a drug page using Playwright (handles JS render)."""
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                page.set_default_timeout(15000)
                await page.goto(url, wait_until="networkidle")
                await page.wait_for_timeout(2000)

                # Extract page content
                content = await page.evaluate("document.body.innerText")
                html = await page.content()
                await browser.close()

                return self._parse_content(content, html, url)
        except Exception as e:
            logger.debug(f"BDMedEx Playwright failed for {url}: {e}")
            return None

    async def _scrape_page(self, url: str) -> Drug | None:
        """Fallback: fetch via bypass and parse."""
        page = await self.fetch_page(url)
        page_text = page.text if hasattr(page, "text") else ""
        return self._parse_content(page_text, page_text, url)

    def _parse_content(self, text: str, html: str, url: str) -> Drug | None:
        """Parse drug data from rendered page text + HTML."""
        if not text or len(text.strip()) < 50:
            return None

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            return None

        # Brand name: first meaningful line (not nav)
        brand_name = ""
        nav_keywords = {"home", "doctors", "clinics", "pharmaceuticals", "brand name",
                        "generics", "news", "search", "privacy", "contact", "bd medex"}
        for line in lines:
            if line.lower() not in nav_keywords and len(line) > 3 and len(line) < 200:
                brand_name = line
                break

        if not brand_name:
            return None

        # Extract key fields from text patterns
        generic_name = _extract_field(text, r"Generic[:\s]+([^\n]{3,80})")
        strength = _extract_field(text, r"Strength[:\s]+([^\n]{2,50})")
        dosage_form = _extract_field(text, r"(?:Dosage\s*Form|Form)[:\s]+([^\n]{3,50})")
        manufacturer_name = _extract_field(text, r"(?:Manufacturer|Company|Marketed\s*by)[:\s]+([^\n]{3,80})")
        price_text = _extract_field(text, r"(?:Price|Unit\s*Price|MRP)[:\s]+([\d.৳]+[^\n]{0,30})")
        therapeutic_class = _extract_field(text, r"Therapeutic\s*Class[:\s]+([^\n]{3,80})")

        # Parse dosage form from brand name if not found
        if not dosage_form:
            name_lower = brand_name.lower()
            for f in _FORMS:
                if f in name_lower:
                    dosage_form = f.title()
                    break

        # Parse strength from brand name if not found
        if not strength:
            sm = re.search(
                r"(\d+(?:\.\d+)?\s*(?:mg|mcg|µg|g|iu|unit|%)(?:/\s*\d+(?:\.\d+)?\s*(?:ml|g|mg))?)",
                brand_name, re.IGNORECASE
            )
            if sm:
                strength = sm.group(1).strip()

        # Extract clinical sections
        sections = _extract_sections(text)
        indications = _split_text(sections.get("indications", sections.get("uses", "")))
        side_effects = _split_text(sections.get("side effects", sections.get("adverse effects", "")))
        contraindications = _split_text(sections.get("contraindications", ""))
        interactions = _split_text(sections.get("drug interactions", sections.get("interactions", "")))
        dosage = sections.get("dosage", sections.get("dosage & administration", ""))
        mechanism = sections.get("mechanism of action", sections.get("pharmacology", ""))
        storage = sections.get("storage", "")
        preg = sections.get("pregnancy", sections.get("pregnancy & lactation", ""))

        # Price parse
        price = None
        if price_text:
            nums = re.findall(r"[\d.]+", price_text)
            if nums:
                price = DrugPrice(amount=float(nums[0]), currency="BDT")

        # Drug type from URL
        is_generic_page = "/generic/" in url

        return Drug(
            source="bdmedex",
            source_url=url,
            brand_name=brand_name if not is_generic_page else None,
            generic_name=generic_name or (brand_name if is_generic_page else None),
            dosage_form=dosage_form or None,
            strength=strength or None,
            therapeutic_class=therapeutic_class or None,
            manufacturer=Manufacturer(name=manufacturer_name, country="Bangladesh") if manufacturer_name else None,
            price=price,
            indications=indications,
            contraindications=contraindications,
            side_effects=side_effects,
            interactions=interactions,
            dosage=dosage or None,
            mechanism_of_action=mechanism or None,
            pregnancy_category=preg[:200] if preg else None,
            storage=storage or None,
            categories=["herbal"] if "herbal" in url.lower() or "herbal" in text.lower()[:200] else [],
            extra={
                "is_veterinary": "veterinary" in text.lower()[:200],
                "is_herbal": "herbal" in text.lower()[:200],
            },
        )


def _extract_field(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_sections(text: str) -> dict[str, str]:
    """Extract named sections from rendered page text."""
    sections: dict[str, str] = {}
    known_sections = [
        "indications", "uses", "contraindications", "side effects", "adverse effects",
        "drug interactions", "interactions", "dosage & administration", "dosage",
        "mechanism of action", "pharmacology", "precautions", "warnings",
        "pregnancy & lactation", "pregnancy", "overdose", "storage",
        "therapeutic class",
    ]
    # Sort by length desc so longer names match first
    known_sections.sort(key=len, reverse=True)

    lines = text.splitlines()
    current_section = ""
    current_content: list[str] = []

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        # Check if this line is a section heading
        matched = False
        for sec in known_sections:
            if line_stripped.lower() == sec or line_stripped.lower().startswith(sec + ":"):
                if current_section and current_content:
                    sections[current_section] = "\n".join(current_content).strip()
                current_section = sec
                current_content = []
                matched = True
                break

        if not matched and current_section:
            current_content.append(line_stripped)

    if current_section and current_content:
        sections[current_section] = "\n".join(current_content).strip()

    return sections


def _split_text(text: str) -> list[str]:
    if not text:
        return []
    items = re.split(r"[•\n;]", text)
    seen = set()
    result = []
    for item in items:
        item = item.strip()
        if item and len(item) > 5 and item not in seen:
            seen.add(item)
            result.append(item)
    return result
