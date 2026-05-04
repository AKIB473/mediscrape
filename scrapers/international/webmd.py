"""WebMD scraper - webmd.com/drugs - A-Z database, interactions, pill ID."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class WebMDScraper(BaseScrapingScraper):
    name = "webmd"
    base_url = "https://www.webmd.com"
    rate_limit = 2.0
    use_stealth = True
    use_dynamic = True  # Playwright needed for heavy CF protection

    async def scrape_all(self) -> AsyncIterator[Drug]:
        urls = await self._get_all_drug_urls()
        logger.info(f"WebMD: found {len(urls)} drug URLs")

        for url in urls:
            try:
                drug = await self._scrape_drug_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"WebMD: error scraping {url}: {e}")

    async def _get_all_drug_urls(self) -> list[str]:
        urls = set()
        # WebMD drug A-Z
        for letter in "abcdefghijklmnopqrstuvwxyz0":
            try:
                page = await self.fetch_page(f"{self.base_url}/drugs/2/alpha/{letter}/list-alpha_a-z-id_1/")
                for link in page.css('a[href*="/drugs/2/drug"]'):
                    href = link.attrib.get("href", "")
                    if href:
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        urls.add(full)

                # Check for additional pages in this letter
                for pg in range(2, 50):
                    try:
                        pg_page = await self.fetch_page(
                            f"{self.base_url}/drugs/2/alpha/{letter}/list-alpha_a-z-id_1/page/{pg}/"
                        )
                        found = 0
                        for link in pg_page.css('a[href*="/drugs/2/drug"]'):
                            href = link.attrib.get("href", "")
                            if href:
                                full = href if href.startswith("http") else f"{self.base_url}{href}"
                                urls.add(full)
                                found += 1
                        if found == 0:
                            break
                    except Exception:
                        break
            except Exception:
                pass
        return list(urls)

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        title = _text(page.css_first("h1"))
        if not title:
            return None

        # Parse title - WebMD format: "Brand Name (Generic Name)"
        brand = title
        generic = ""
        if "(" in title and ")" in title:
            brand = title.split("(")[0].strip()
            generic = title.split("(")[1].rstrip(")").strip()

        sections = {}
        for h2 in page.css("h2, h3, .drug-section-title"):
            key = _text(h2).lower()
            content = []
            nxt = h2
            for _ in range(30):
                nxt = nxt.css_first("+ p, + ul, + div.drug-content")
                if nxt is None:
                    break
                t = _text(nxt)
                if t:
                    content.append(t)
            if content:
                sections[key] = "\n".join(content)

        # Extract interactions list
        interactions = []
        int_section = page.css_first('[class*="interactions"], [id*="interactions"]')
        if int_section:
            for li in int_section.css("li, a"):
                t = _text(li)
                if t:
                    interactions.append(t)

        return Drug(
            source="webmd",
            source_url=url,
            brand_name=brand,
            generic_name=generic,
            description=sections.get("uses", sections.get("what is", "")),
            indications=_split(sections.get("uses", "")),
            side_effects=_split(sections.get("side effects", "")),
            warnings=_split(sections.get("precautions", sections.get("warnings", ""))),
            interactions=interactions or _split(sections.get("interactions", "")),
            dosage=sections.get("how to use", sections.get("dosage", "")),
            overdose=sections.get("overdose", ""),
            storage=sections.get("storage", ""),
            extra={
                "jsonld": jsonld,
                "sections": sections,
                "notes": sections.get("notes", ""),
                "missed_dose": sections.get("missed dose", ""),
            },
        )


def _text(elem) -> str:
    if elem is None:
        return ""
    return elem.text.strip() if hasattr(elem, "text") and elem.text else ""


def _split(text: str) -> list[str]:
    if not text:
        return []
    return [i.strip() for i in re.split(r"[•\n]", text) if i.strip()]
