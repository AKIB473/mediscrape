"""MIMS (Asia) scraper - mims.com - Drug reference across Asia-Pacific."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class MIMSScraper(BaseScrapingScraper):
    name = "mims"
    base_url = "https://www.mims.com"
    rate_limit = 2.0
    use_stealth = True
    use_dynamic = True  # Playwright needed for heavy CF protection

    async def scrape_all(self) -> AsyncIterator[Drug]:
        urls = await self._get_drug_urls()
        logger.info(f"MIMS: found {len(urls)} drug URLs")

        for url in urls:
            try:
                drug = await self._scrape_drug_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"MIMS: error scraping {url}: {e}")

    async def _get_drug_urls(self) -> list[str]:
        urls = set()

        # MIMS Bangladesh section
        for letter in "abcdefghijklmnopqrstuvwxyz":
            for region in ["bangladesh", ""]:
                try:
                    path = f"/{region}/browse/drug/{letter}" if region else f"/browse/drug/{letter}"
                    page = await self.fetch_page(f"{self.base_url}{path}")
                    for link in page.css('a[href*="/drug/"]'):
                        href = link.attrib.get("href", "")
                        if href and "/drug/" in href and "/browse/" not in href:
                            full = href if href.startswith("http") else f"{self.base_url}{href}"
                            urls.add(full)
                except Exception:
                    pass

        return list(urls)

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        title = _text(page.css_first("h1"))
        if not title:
            return None

        sections = {}
        for section in page.css(".drug-section, .monograph-section, [class*=section]"):
            heading = _text(section.css_first("h2, h3, .section-title"))
            content = _text(section)
            if heading:
                sections[heading.lower()] = content

        # Extract fields
        fields = {}
        for row in page.css("tr, .detail-item"):
            label = _text(row.css_first("th, .label"))
            value = _text(row.css_first("td, .value"))
            if label and value:
                fields[label.lower().strip().rstrip(":")] = value

        generic = fields.get("generic", fields.get("active ingredient", ""))
        manufacturer_name = fields.get("manufacturer", fields.get("company", ""))
        atc = fields.get("atc", fields.get("atc code", ""))

        return Drug(
            source="mims",
            source_url=url,
            brand_name=title,
            generic_name=generic,
            atc_code=atc,
            manufacturer=Manufacturer(name=manufacturer_name) if manufacturer_name else None,
            dosage_form=fields.get("dosage form", fields.get("form", "")),
            strength=fields.get("strength", ""),
            indications=_split(sections.get("indications", sections.get("indication", ""))),
            contraindications=_split(sections.get("contraindications", "")),
            side_effects=_split(sections.get("adverse effects", sections.get("side effects", ""))),
            warnings=_split(sections.get("special precautions", sections.get("warnings", ""))),
            interactions=_split(sections.get("drug interactions", sections.get("interactions", ""))),
            dosage=sections.get("dosage", sections.get("dosage/direction for use", "")),
            mechanism_of_action=sections.get("action", sections.get("mechanism of action", "")),
            pharmacokinetics={"description": sections.get("pharmacokinetics", "")} if sections.get("pharmacokinetics") else None,
            pregnancy_category=sections.get("pregnancy", fields.get("pregnancy category", "")),
            storage=sections.get("storage", fields.get("storage", "")),
            description=sections.get("description", ""),
            extra={
                "jsonld": jsonld,
                "mims_class": fields.get("mims class", ""),
                "presentation": sections.get("presentation/packing", ""),
                "overdosage": sections.get("overdosage", ""),
                "caution": sections.get("cautions", ""),
                "sections": sections,
                "fields": fields,
            },
        )


def _text(elem) -> str:
    if elem is None:
        return ""
    return elem.text.strip() if hasattr(elem, "text") and elem.text else ""


def _split(text: str) -> list[str]:
    if not text:
        return []
    return [i.strip() for i in re.split(r"[•\n;]", text) if i.strip()]
