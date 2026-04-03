"""BD Medex scraper - bdmedex.com - 35k+ brands, herbal + veterinary included."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class BDMedExScraper(BaseScrapingScraper):
    name = "bdmedex"
    base_url = "https://bdmedex.com"
    rate_limit = 1.0

    async def scrape_all(self) -> AsyncIterator[Drug]:
        all_urls = set()

        # Scrape generic index
        for letter in "abcdefghijklmnopqrstuvwxyz0":
            try:
                page = await self.fetch_page(f"{self.base_url}/generics/{letter}")
                for link in page.css('a[href*="/generic/"], a[href*="/generics/"]'):
                    href = link.attrib.get("href", "")
                    if href and len(href) > 10:
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        all_urls.add(full)
            except Exception:
                pass

        # Also scrape brand index
        for letter in "abcdefghijklmnopqrstuvwxyz0":
            try:
                page = await self.fetch_page(f"{self.base_url}/brands/{letter}")
                for link in page.css('a[href*="/brand/"]'):
                    href = link.attrib.get("href", "")
                    if href:
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        all_urls.add(full)
            except Exception:
                pass

        logger.info(f"BDMedEx: found {len(all_urls)} drug URLs")

        for url in all_urls:
            try:
                drug = await self._scrape_drug_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"BDMedEx: error scraping {url}: {e}")

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        title = _text(page.css_first("h1"))
        if not title:
            return None

        # Extract all section data
        sections = {}
        for heading in page.css("h2, h3, h4, .section-heading"):
            key = _text(heading).lower().strip()
            next_elem = heading
            content = []
            # Collect text until next heading
            parent = heading.parent
            if parent:
                for child in parent.css("p, ul, ol, div, span"):
                    t = _text(child)
                    if t and len(t) > 3:
                        content.append(t)
            if content:
                sections[key] = "\n".join(content)

        # Extract key-value fields
        fields = {}
        for row in page.css("tr, .info-row, .detail-row, dt"):
            cells = row.css("td, dd")
            label_elem = row.css_first("th, .label, dt")
            if label_elem and cells:
                key = _text(label_elem).lower().strip().rstrip(":")
                val = _text(cells[0])
                if key and val:
                    fields[key] = val

        generic_name = fields.get("generic", fields.get("generic name", ""))
        brand_name = fields.get("brand name", fields.get("brand", title))
        manufacturer_name = fields.get("manufacturer", fields.get("company", ""))
        dosage_form = fields.get("dosage form", fields.get("form", ""))
        strength = fields.get("strength", fields.get("dose", ""))
        price_text = fields.get("price", fields.get("unit price", fields.get("mrp", "")))
        drug_type = fields.get("type", fields.get("category", ""))

        price = _parse_price(price_text) if price_text else None

        return Drug(
            source="bdmedex",
            source_url=url,
            brand_name=brand_name,
            generic_name=generic_name,
            dosage_form=dosage_form,
            strength=strength,
            manufacturer=Manufacturer(name=manufacturer_name, country="Bangladesh") if manufacturer_name else None,
            price=price,
            therapeutic_class=drug_type,
            indications=_split(sections.get("indications", sections.get("indication", ""))),
            contraindications=_split(sections.get("contraindications", "")),
            side_effects=_split(sections.get("side effects", sections.get("adverse effects", ""))),
            interactions=_split(sections.get("interactions", sections.get("drug interactions", ""))),
            dosage=sections.get("dosage", sections.get("dose", "")),
            mechanism_of_action=sections.get("mode of action", sections.get("pharmacology", "")),
            pregnancy_category=sections.get("pregnancy", fields.get("pregnancy category", "")),
            storage=sections.get("storage", ""),
            warnings=_split(sections.get("warnings", "")),
            precautions=_split(sections.get("precautions", "")),
            description=sections.get("description", ""),
            categories=[drug_type] if drug_type else [],
            extra={
                "jsonld": jsonld,
                "includes_herbal": "herbal" in drug_type.lower() if drug_type else False,
                "includes_veterinary": "veterinary" in drug_type.lower() if drug_type else False,
                "all_fields": fields,
                "sections": sections,
            },
        )


def _text(elem) -> str:
    if elem is None:
        return ""
    return elem.text.strip() if hasattr(elem, "text") and elem.text else ""


def _parse_price(text: str) -> DrugPrice | None:
    if not text:
        return None
    nums = re.findall(r"[\d.]+", text)
    if nums:
        return DrugPrice(amount=float(nums[0]), currency="BDT", unit=text)
    return None


def _split(text: str) -> list[str]:
    if not text:
        return []
    return [i.strip() for i in re.split(r"[•\n;]", text) if i.strip()]
