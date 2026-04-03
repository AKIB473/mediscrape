"""DGDA scraper - dgda.gov.bd - Official govt drug prices, registered drugs.

Note: DGDA site has known SSL certificate issues. May need verify=False.
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class DGDAScraper(BaseScrapingScraper):
    name = "dgda"
    base_url = "https://dgda.gov.bd"
    rate_limit = 2.0  # Be very polite to govt site
    use_stealth = True  # Govt sites can be finicky

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # DGDA has drug search at /service/drug-search or similar
        # Try to find drug listing pages
        drug_urls = await self._get_drug_urls()
        logger.info(f"DGDA: found {len(drug_urls)} drug URLs")

        for url in drug_urls:
            try:
                drug = await self._scrape_drug_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"DGDA: error scraping {url}: {e}")

    async def _get_drug_urls(self) -> list[str]:
        urls = set()

        # Try the main drug search/list pages
        search_paths = [
            "/service/drug-search",
            "/services/drug",
            "/drug",
            "/medicine",
            "/registered-drugs",
        ]

        for path in search_paths:
            try:
                page = await self.fetch_page(f"{self.base_url}{path}")
                # Look for drug links
                for link in page.css("a"):
                    href = link.attrib.get("href", "")
                    if any(kw in href.lower() for kw in ["/drug/", "/medicine/", "/product/"]):
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        urls.add(full)

                # Check for pagination
                next_links = page.css('a[rel="next"], .pagination a, .next a')
                for nl in next_links:
                    href = nl.attrib.get("href", "")
                    if href:
                        try:
                            next_page = await self.fetch_page(
                                href if href.startswith("http") else f"{self.base_url}{href}"
                            )
                            for link in next_page.css("a"):
                                h = link.attrib.get("href", "")
                                if any(kw in h.lower() for kw in ["/drug/", "/medicine/"]):
                                    full = h if h.startswith("http") else f"{self.base_url}{h}"
                                    urls.add(full)
                        except Exception:
                            pass
            except Exception:
                pass

        # Try scraping drug price list pages
        try:
            page = await self.fetch_page(f"{self.base_url}")
            # Look for any link containing drug/medicine/price
            for link in page.css("a"):
                href = link.attrib.get("href", "")
                text = _text(link).lower()
                if any(kw in text for kw in ["drug", "medicine", "price"]):
                    full = href if href.startswith("http") else f"{self.base_url}{href}"
                    urls.add(full)
        except Exception:
            pass

        return list(urls)

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        # Try to extract data from table rows
        tables = page.css("table")
        for table in tables:
            rows = table.css("tr")
            for row in rows:
                cells = row.css("td, th")
                if len(cells) >= 3:
                    data = {_text(cells[0]).lower(): _text(cells[1])}

        # Extract key-value pairs from the page
        fields = {}
        for dt in page.css("dt, .label, th"):
            key = _text(dt).lower().strip().rstrip(":")
            dd = dt.css_first("+ dd, + td")
            if dd:
                fields[key] = _text(dd)

        # Try extracting from any structured layout
        title = _text(page.css_first("h1, h2, .title, .drug-name"))

        brand_name = fields.get("brand name", fields.get("brand", title))
        generic_name = fields.get("generic name", fields.get("generic", fields.get("molecule", "")))
        dosage_form = fields.get("dosage form", fields.get("form", ""))
        strength = fields.get("strength", fields.get("dose", ""))
        manufacturer_name = fields.get("manufacturer", fields.get("company", fields.get("marketing company", "")))
        price_text = fields.get("price", fields.get("mrp", fields.get("unit price", "")))
        reg_no = fields.get("registration no", fields.get("dar no", fields.get("registration number", "")))

        if not brand_name and not generic_name:
            return None

        price = _parse_price(price_text) if price_text else None

        return Drug(
            source="dgda",
            source_url=url,
            brand_name=brand_name,
            generic_name=generic_name,
            dosage_form=dosage_form,
            strength=strength,
            manufacturer=Manufacturer(name=manufacturer_name, country="Bangladesh") if manufacturer_name else None,
            price=price,
            registration_number=reg_no,
            extra={
                "jsonld": jsonld,
                "all_fields": fields,
                "official_govt_data": True,
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
