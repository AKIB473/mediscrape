"""MedEasy scraper - medeasy.health - Online pharmacy."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class MedEasyScraper(BaseScrapingScraper):
    name = "medeasy"
    base_url = "https://medeasy.health"
    rate_limit = 1.5
    use_stealth = True
    use_dynamic = True  # Full Next.js CSR; needs Playwright to hydrate product data

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Try API discovery first
        api_data = await self._try_api()
        if api_data:
            for drug in api_data:
                yield drug
            return

        # Fallback to HTML scraping
        urls = await self._get_drug_urls()
        logger.info(f"MedEasy: found {len(urls)} drug URLs")

        for url in urls:
            try:
                drug = await self._scrape_drug_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"MedEasy: error scraping {url}: {e}")

    async def _try_api(self) -> list[Drug]:
        """Try to find hidden API endpoints."""
        drugs = []
        api_paths = [
            "/api/products", "/api/medicines", "/api/v1/products",
            "/api/v1/medicines", "/api/search",
        ]

        for path in api_paths:
            try:
                page = await self.fetch_page(f"{self.base_url}{path}")
                if page.status == 200:
                    import orjson
                    try:
                        data = orjson.loads(page.text)
                        items = data if isinstance(data, list) else data.get("data", data.get("results", []))
                        if isinstance(items, list):
                            for item in items:
                                drug = self._parse_api_item(item)
                                if drug:
                                    drugs.append(drug)
                            if drugs:
                                logger.info(f"MedEasy: found API at {path}")
                                return drugs
                    except Exception:
                        pass
            except Exception:
                pass

        return drugs

    def _parse_api_item(self, item: dict) -> Drug | None:
        name = item.get("name") or item.get("title")
        if not name:
            return None

        price_val = item.get("price") or item.get("mrp")
        price = DrugPrice(amount=float(price_val), currency="BDT") if price_val else None

        return Drug(
            source="medeasy",
            source_url=f"{self.base_url}/medicine/{item.get('slug', item.get('id', ''))}",
            source_id=str(item.get("id", "")),
            brand_name=name,
            generic_name=item.get("generic_name") or item.get("generic"),
            dosage_form=item.get("dosage_form") or item.get("form"),
            strength=item.get("strength"),
            manufacturer=Manufacturer(name=item["manufacturer"]) if item.get("manufacturer") else None,
            price=price,
            description=item.get("description"),
            extra={k: v for k, v in item.items() if k not in ("name", "title", "generic_name", "generic", "price", "mrp", "description")},
        )

    async def _get_drug_urls(self) -> list[str]:
        urls = set()
        # MedEasy is fully CSR — try multiple listing paths with Playwright
        listing_paths = [
            "/medicines", "/products", "/pharmacy", "/shop",
            "/category/medicine", "/all-medicines",
        ]
        for path in listing_paths:
            for page_num in range(1, 30):
                try:
                    page = await self.fetch_page(
                        f"{self.base_url}{path}?page={page_num}"
                    )
                    found = 0
                    for link in page.css(
                        'a[href*="/medicine/"], a[href*="/product/"], a[href*="/drug/"]'
                    ):
                        href = link.attrib.get("href", "")
                        if href:
                            full = href if href.startswith("http") else f"{self.base_url}{href}"
                            urls.add(full)
                            found += 1
                    if found == 0:
                        break
                except Exception:
                    break
        return list(urls)

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        # Check __NEXT_DATA__
        next_script = page.css_first('script#__NEXT_DATA__')
        if next_script:
            try:
                import orjson
                data = orjson.loads(next_script.text)
                product = data.get("props", {}).get("pageProps", {}).get("product", {})
                if product:
                    drug = self._parse_api_item(product)
                    if drug:
                        drug.source_url = url
                        return drug
            except Exception:
                pass

        title = _text(page.css_first("h1"))
        if not title:
            return None

        fields = {}
        for row in page.css("tr, .info-row"):
            label = _text(row.css_first("th, .label"))
            value = _text(row.css_first("td, .value"))
            if label and value:
                fields[label.lower().strip().rstrip(":")] = value

        return Drug(
            source="medeasy",
            source_url=url,
            brand_name=title,
            generic_name=fields.get("generic", ""),
            dosage_form=fields.get("form", ""),
            strength=fields.get("strength", ""),
            manufacturer=Manufacturer(name=fields["company"]) if fields.get("company") else None,
            price=_parse_price(fields.get("price", "")),
            extra={"jsonld": jsonld, "fields": fields},
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
