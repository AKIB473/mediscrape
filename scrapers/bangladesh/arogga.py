"""Arogga scraper - arogga.com - 32k+ medicines, online pharmacy.

Structure (from research):
- Next.js app with sitemaps at /sitemap/0.xml through /sitemap/19.xml
- Product URLs: /product/{id}/{name}
- __NEXT_DATA__ available on product pages
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

import orjson
from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class AroggaScraper(BaseScrapingScraper):
    name = "arogga"
    base_url = "https://www.arogga.com"
    rate_limit = 1.0
    use_stealth = True

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Discover product URLs from sitemaps
        urls = await self._get_product_urls_from_sitemaps()
        logger.info(f"Arogga: found {len(urls)} product URLs from sitemaps")

        # Fallback: paginated listing
        if not urls:
            urls = await self._get_product_urls_from_listing()
            logger.info(f"Arogga: found {len(urls)} product URLs from listing")

        for url in urls:
            try:
                drug = await self._scrape_product_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"Arogga: error scraping {url}: {e}")

    async def _get_product_urls_from_sitemaps(self) -> list[str]:
        urls = set()
        # Arogga has sitemaps at /sitemap/0.xml through /sitemap/19.xml
        for i in range(20):
            try:
                page = await self.fetch_page(f"{self.base_url}/sitemap/{i}.xml")
                # Parse XML sitemap - look for <loc> tags
                for loc in page.css("loc, url loc"):
                    url_text = _text(loc)
                    if url_text and "/product/" in url_text:
                        urls.add(url_text)
                # Also try text-based extraction if CSS doesn't work on XML
                if not urls:
                    text = page.text if hasattr(page, "text") else ""
                    for match in re.findall(r"<loc>(https?://[^<]+/product/[^<]+)</loc>", text):
                        urls.add(match)
            except Exception as e:
                logger.debug(f"Arogga: sitemap {i} failed: {e}")
                if i > 2 and not urls:
                    break  # No sitemaps found

        return list(urls)

    async def _get_product_urls_from_listing(self) -> list[str]:
        urls = set()
        for page_num in range(1, 500):
            try:
                page = await self.fetch_page(f"{self.base_url}/medicine?page={page_num}")
                found = 0
                for link in page.css('a[href*="/product/"]'):
                    href = link.attrib.get("href", "")
                    if href:
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        urls.add(full)
                        found += 1

                # Also try __NEXT_DATA__ for product list
                if found == 0:
                    next_data = self._extract_next_data(page)
                    if next_data:
                        props = next_data.get("props", {}).get("pageProps", {})
                        products = props.get("products", props.get("medicines", props.get("data", [])))
                        if isinstance(products, list):
                            for p in products:
                                pid = p.get("id") or p.get("_id") or ""
                                slug = p.get("slug") or p.get("alias") or ""
                                if pid:
                                    urls.add(f"{self.base_url}/product/{pid}/{slug}")
                                    found += 1

                if found == 0:
                    break
            except Exception:
                break

        return list(urls)

    async def _scrape_product_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)

        # Primary: __NEXT_DATA__
        next_data = self._extract_next_data(page)
        if next_data:
            props = next_data.get("props", {}).get("pageProps", {})
            product = props.get("product") or props.get("medicine") or props.get("data", {})
            if isinstance(product, dict) and product:
                return self._parse_product(product, url)

        # Secondary: JSON-LD
        jsonld = self.extract_jsonld(page)
        for ld in jsonld:
            if ld.get("@type") == "Product":
                return self._parse_jsonld(ld, url)

        # Fallback: HTML
        return self._parse_html(page, url, jsonld)

    def _extract_next_data(self, page) -> dict | None:
        script = page.css_first('script#__NEXT_DATA__')
        if script and script.text:
            try:
                return orjson.loads(script.text)
            except Exception:
                pass
        return None

    def _parse_product(self, item: dict, url: str) -> Drug | None:
        name = item.get("name") or item.get("title") or item.get("brand_name")
        if not name:
            return None

        price_val = item.get("price") or item.get("mrp") or item.get("unit_price")
        price = None
        if price_val:
            try:
                price = DrugPrice(amount=float(price_val), currency="BDT")
            except (ValueError, TypeError):
                pass

        mfr = item.get("manufacturer") or item.get("company") or ""
        slug = item.get("slug") or item.get("id", "")

        return Drug(
            source="arogga",
            source_url=url,
            source_id=str(item.get("id", "")),
            brand_name=name,
            generic_name=item.get("generic_name") or item.get("generic") or item.get("molecule"),
            dosage_form=item.get("dosage_form") or item.get("form"),
            strength=item.get("strength") or item.get("dose"),
            manufacturer=Manufacturer(name=mfr, country="Bangladesh") if mfr else None,
            price=price,
            description=item.get("description"),
            image_url=item.get("image") or item.get("thumbnail"),
            categories=[item["category"]] if isinstance(item.get("category"), str) else [],
            extra={
                k: v for k, v in item.items()
                if k not in ("name", "title", "brand_name", "generic_name", "generic",
                             "molecule", "dosage_form", "form", "strength", "dose",
                             "manufacturer", "company", "price", "mrp", "unit_price",
                             "description", "image", "thumbnail", "category", "slug", "id")
            },
        )

    def _parse_jsonld(self, ld: dict, url: str) -> Drug:
        offers = ld.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        return Drug(
            source="arogga",
            source_url=url,
            brand_name=ld.get("name"),
            description=ld.get("description"),
            image_url=ld.get("image"),
            price=DrugPrice(
                amount=float(offers["price"]),
                currency=offers.get("priceCurrency", "BDT"),
            ) if offers.get("price") else None,
            extra={"jsonld": ld},
        )

    def _parse_html(self, page, url: str, jsonld: list) -> Drug | None:
        title = _text(page.css_first("h1"))
        if not title:
            return None

        fields = {}
        for row in page.css("tr, .info-row, .detail-item"):
            label = _text(row.css_first("th, .label, dt"))
            value = _text(row.css_first("td, .value, dd"))
            if label and value:
                fields[label.lower().strip().rstrip(":")] = value

        price_text = _text(page.css_first(".price, [class*=price]"))

        return Drug(
            source="arogga",
            source_url=url,
            brand_name=title,
            generic_name=fields.get("generic", fields.get("generic name", "")),
            dosage_form=fields.get("form", fields.get("dosage form", "")),
            strength=fields.get("strength", ""),
            manufacturer=Manufacturer(name=fields["manufacturer"], country="Bangladesh") if fields.get("manufacturer") else None,
            price=_parse_price(price_text),
            description=_text(page.css_first(".description, [class*=description]")),
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
