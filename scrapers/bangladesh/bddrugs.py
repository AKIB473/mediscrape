"""BDdrugs scraper - bddrugs.com - Drug index since 2010, prices, dosage forms."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class BDDrugsScraper(BaseScrapingScraper):
    name = "bddrugs"
    base_url = "https://www.bddrugs.com"
    rate_limit = 1.5
    # NOTE: bddrugs.com returns HTTP 522 (Connection Timed Out) / is currently offline.
    # Scraper will gracefully yield nothing when the site is unreachable.

    async def scrape_all(self) -> AsyncIterator[Drug]:
        urls = set()

        # Fast reachability check via httpx (bypasses scrapling's 3-attempt retry)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as _c:
                _r = await _c.get(f"{self.base_url}/")
            if _r.status_code not in (200, 301, 302, 403):
                logger.warning(f"BDDrugs: site returned {_r.status_code}, skipping")
                return
        except Exception as e:
            logger.warning(f"BDDrugs: site unreachable ({e}), skipping")
            return

        # Try multiple index patterns
        index_paths = [
            "/drug-index",
            "/drugs",
            "/medicine",
            "/generic",
            "/brand",
        ]

        for path in index_paths:
            try:
                page = await self.fetch_page(f"{self.base_url}{path}")
                for link in page.css("a"):
                    href = link.attrib.get("href", "")
                    if href and any(kw in href for kw in ["/drug/", "/medicine/", "/generic/", "/brand/"]):
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        urls.add(full)
            except Exception:
                pass

        # Try A-Z pages
        for letter in "abcdefghijklmnopqrstuvwxyz":
            for path_tpl in ["/drug-index/{}", "/drugs/{}", "/drugs?letter={}"]:
                try:
                    page = await self.fetch_page(f"{self.base_url}{path_tpl.format(letter)}")
                    for link in page.css("a"):
                        href = link.attrib.get("href", "")
                        if href and "/drug" in href.lower():
                            full = href if href.startswith("http") else f"{self.base_url}{href}"
                            urls.add(full)
                except Exception:
                    pass

        logger.info(f"BDDrugs: found {len(urls)} drug URLs")

        for url in urls:
            try:
                drug = await self._scrape_drug_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"BDDrugs: error scraping {url}: {e}")

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        title = _text(page.css_first("h1, .drug-title"))
        if not title:
            return None

        # Extract all info from key-value pairs and sections
        fields = {}
        for row in page.css("tr, .info-item, dt, .field-label"):
            label = _text(row.css_first("th, .label, dt, .field-label"))
            value = _text(row.css_first("td, .value, dd, .field-value"))
            if not label:
                label = _text(row)
            if label and value:
                fields[label.lower().strip().rstrip(":")] = value

        sections = {}
        for h in page.css("h2, h3, h4"):
            key = _text(h).lower()
            sibling_text = []
            for sib in page.css(f"h2 ~ p, h3 ~ p, h4 ~ p"):
                t = _text(sib)
                if t:
                    sibling_text.append(t)
            if sibling_text:
                sections[key] = "\n".join(sibling_text[:5])

        return Drug(
            source="bddrugs",
            source_url=url,
            brand_name=fields.get("brand name", fields.get("brand", title)),
            generic_name=fields.get("generic name", fields.get("generic", "")),
            dosage_form=fields.get("dosage form", fields.get("form", "")),
            strength=fields.get("strength", fields.get("dose", "")),
            manufacturer=Manufacturer(
                name=fields.get("manufacturer", fields.get("company", "")),
                country="Bangladesh",
            ) if fields.get("manufacturer") or fields.get("company") else None,
            price=_parse_price(fields.get("price", fields.get("mrp", fields.get("unit price", "")))),
            therapeutic_class=fields.get("therapeutic class", fields.get("class", "")),
            indications=_split(sections.get("indications", fields.get("indications", ""))),
            contraindications=_split(sections.get("contraindications", "")),
            side_effects=_split(sections.get("side effects", "")),
            interactions=_split(sections.get("interactions", "")),
            dosage=sections.get("dosage", fields.get("dosage", "")),
            pregnancy_category=fields.get("pregnancy category", ""),
            storage=fields.get("storage", sections.get("storage", "")),
            description=sections.get("description", ""),
            extra={
                "jsonld": jsonld,
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
