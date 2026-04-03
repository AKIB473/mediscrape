"""WHO Essential Medicines List scraper - 523 essential medications."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class WHOEMLScraper(BaseScrapingScraper):
    name = "who_eml"
    base_url = "https://list.essentialmeds.org"
    rate_limit = 1.5

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # WHO EML is available at list.essentialmeds.org
        # Try the API/data endpoint first
        try:
            page = await self.fetch_page(f"{self.base_url}/medicines")
            jsonld = self.extract_jsonld(page)

            # Try to find data in page scripts
            for script in page.css("script"):
                text = script.text if hasattr(script, "text") and script.text else ""
                if "medicines" in text.lower() and "{" in text:
                    try:
                        import orjson
                        # Find JSON data in script
                        start = text.index("{")
                        data = orjson.loads(text[start:])
                        items = data.get("medicines", data.get("data", []))
                        if isinstance(items, list):
                            for item in items:
                                drug = self._parse_medicine(item)
                                if drug:
                                    yield drug
                            return
                    except Exception:
                        pass
        except Exception:
            pass

        # Fallback: scrape the medicine list page
        try:
            page = await self.fetch_page(f"{self.base_url}")

            # Get all medicine links
            links = page.css('a[href*="/medicines/"], a[href*="/medicine/"]')
            urls = set()
            for link in links:
                href = link.attrib.get("href", "")
                if href:
                    full = href if href.startswith("http") else f"{self.base_url}{href}"
                    urls.add(full)

            logger.info(f"WHO EML: found {len(urls)} medicine URLs")

            for url in urls:
                try:
                    drug = await self._scrape_medicine_page(url)
                    if drug:
                        yield drug
                except Exception as e:
                    logger.warning(f"WHO EML: error scraping {url}: {e}")
        except Exception as e:
            logger.error(f"WHO EML: failed to load main page: {e}")

        # Also try the WHO main site
        try:
            page = await self.fetch_page("https://www.who.int/groups/expert-committee-on-selection-and-use-of-essential-medicines/essential-medicines-lists")
            for link in page.css('a[href*="essential"]'):
                href = link.attrib.get("href", "")
                logger.debug(f"WHO link: {href}")
        except Exception:
            pass

    def _parse_medicine(self, item: dict) -> Drug | None:
        name = item.get("name") or item.get("title") or item.get("inn")
        if not name:
            return None

        return Drug(
            source="who_eml",
            source_url=f"{self.base_url}/medicines/{item.get('id', '')}",
            source_id=str(item.get("id", "")),
            generic_name=name,
            dosage_form=item.get("dosage_form") or item.get("form"),
            strength=item.get("strength") or item.get("dose"),
            route=item.get("route"),
            therapeutic_class=item.get("section") or item.get("category"),
            categories=[item["section"]] if item.get("section") else [],
            extra={
                "eml_section": item.get("section"),
                "eml_subsection": item.get("subsection"),
                "complementary": item.get("complementary", False),
                "age_group": item.get("age_group"),
                "formulation_type": item.get("formulation_type"),
                "notes": item.get("notes"),
                "square_box": item.get("square_box"),  # Therapeutic equivalence marker
                "who_list_number": item.get("list_number"),
            },
        )

    async def _scrape_medicine_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        title = _text(page.css_first("h1, .medicine-name"))
        if not title:
            return None

        fields = {}
        for row in page.css("tr, .detail-item, dt"):
            label = _text(row.css_first("th, .label, dt"))
            value = _text(row.css_first("td, .value, dd"))
            if label and value:
                fields[label.lower().strip().rstrip(":")] = value

        return Drug(
            source="who_eml",
            source_url=url,
            generic_name=title,
            dosage_form=fields.get("dosage form", fields.get("form", "")),
            strength=fields.get("strength", ""),
            route=fields.get("route", ""),
            therapeutic_class=fields.get("section", fields.get("category", "")),
            extra={
                "jsonld": jsonld,
                "all_fields": fields,
                "who_essential": True,
            },
        )


def _text(elem) -> str:
    if elem is None:
        return ""
    return elem.text.strip() if hasattr(elem, "text") and elem.text else ""
