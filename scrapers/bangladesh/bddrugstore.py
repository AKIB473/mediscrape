"""BD Drugstore scraper - bddrugstore.com - Drug index + doctors directory."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class BDDrugstoreScraper(BaseScrapingScraper):
    name = "bddrugstore"
    base_url = "https://www.bddrugstore.com"
    rate_limit = 1.5
    # NOTE: bddrugstore.com DNS does not resolve — site is offline/defunct.
    # Scraper will gracefully yield nothing when the site is unreachable.

    async def scrape_all(self) -> AsyncIterator[Drug]:
        urls = set()

        # Fast DNS/reachability check via httpx (bypasses scrapling's 3-attempt retry)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=6, follow_redirects=True) as _c:
                _r = await _c.get(f"{self.base_url}/")
        except httpx.ConnectError as e:
            logger.warning(f"BDDrugstore: site unreachable ({e}), skipping")
            return
        except Exception as e:
            logger.warning(f"BDDrugstore: connection failed ({e}), skipping")
            return
        if _r.status_code not in (200, 301, 302, 403):
            logger.warning(f"BDDrugstore: site returned {_r.status_code}, skipping")
            return

        # Navigate drug index
        index_paths = ["/drug", "/drugs", "/medicine", "/brand", "/generic"]
        for path in index_paths:
            try:
                page = await self.fetch_page(f"{self.base_url}{path}")
                for link in page.css("a"):
                    href = link.attrib.get("href", "")
                    if href and any(kw in href.lower() for kw in ["/drug/", "/medicine/", "/brand/", "/generic/"]):
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        urls.add(full)
            except Exception:
                pass

        # A-Z index
        for letter in "abcdefghijklmnopqrstuvwxyz":
            try:
                page = await self.fetch_page(f"{self.base_url}/drug?letter={letter}")
                for link in page.css("a"):
                    href = link.attrib.get("href", "")
                    if href and "/drug" in href.lower():
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        urls.add(full)
            except Exception:
                pass

        logger.info(f"BDDrugstore: found {len(urls)} drug URLs")

        for url in urls:
            try:
                drug = await self._scrape_drug_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"BDDrugstore: error scraping {url}: {e}")

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        title = _text(page.css_first("h1"))
        if not title:
            return None

        fields = {}
        for row in page.css("tr, .detail-item, dt"):
            label = _text(row.css_first("th, .label, dt"))
            value = _text(row.css_first("td, .value, dd"))
            if label and value:
                fields[label.lower().strip().rstrip(":")] = value

        sections = {}
        for h in page.css("h2, h3, h4"):
            key = _text(h).lower()
            next_p = h.css_first("+ p, + div, + ul")
            if next_p:
                sections[key] = _text(next_p)

        return Drug(
            source="bddrugstore",
            source_url=url,
            brand_name=fields.get("brand name", fields.get("brand", title)),
            generic_name=fields.get("generic name", fields.get("generic", "")),
            dosage_form=fields.get("dosage form", fields.get("form", "")),
            strength=fields.get("strength", ""),
            manufacturer=Manufacturer(
                name=fields.get("manufacturer", fields.get("company", "")),
                country="Bangladesh",
            ) if fields.get("manufacturer") or fields.get("company") else None,
            price=_parse_price(fields.get("price", fields.get("mrp", ""))),
            therapeutic_class=fields.get("class", fields.get("therapeutic class", "")),
            indications=_split(sections.get("indications", "")),
            contraindications=_split(sections.get("contraindications", "")),
            side_effects=_split(sections.get("side effects", "")),
            interactions=_split(sections.get("interactions", "")),
            dosage=sections.get("dosage", fields.get("dosage", "")),
            description=sections.get("description", ""),
            extra={
                "jsonld": jsonld,
                "all_fields": fields,
                "sections": sections,
                "has_doctor_directory": True,
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
