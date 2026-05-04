"""Arogga scraper - arogga.com - 32k+ medicines, online pharmacy.

Structure (verified 2026-05):
- Next.js 13+ App Router (no __NEXT_DATA__; RSC streaming)
- Sitemaps at /sitemap.xml (index) → /sitemap/0.xml … /sitemap/19.xml (3 k URLs each)
- Product URLs: /product/{id}/{slug}
- Product data exposed in JSON-LD <script type="application/ld+json">
- RSC payload in self.__next_f.push() — parsed for extra fields
- p_name, p_form, p_strength, generic_name present in RSC blocks
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

        # Step 1: Fetch sitemap index to discover all sub-sitemaps dynamically
        sitemap_paths = []
        try:
            index_page = await self.fetch_page(f"{self.base_url}/sitemap.xml")
            index_text = index_page.text if hasattr(index_page, "text") else ""
            discovered = re.findall(
                r"<loc>(https?://[^<]+/sitemap/[^<]+\.xml)</loc>", index_text
            )
            # Only keep medicine/product sitemaps (exclude lab, lab0, etc.)
            sitemap_paths = [
                u for u in discovered
                if re.search(r"/sitemap/\d+\.xml", u)
            ]
            logger.info(f"Arogga: found {len(sitemap_paths)} product sitemaps")
        except Exception:
            # Fallback: try numbered sitemaps 0-19
            sitemap_paths = [f"{self.base_url}/sitemap/{i}.xml" for i in range(20)]

        for sitemap_url in sitemap_paths:
            try:
                page = await self.fetch_page(sitemap_url)
                text = page.text if hasattr(page, "text") else ""
                for match in re.findall(r"<loc>(https?://[^<]+/product/[^<]+)</loc>", text):
                    urls.add(match)
                logger.debug(f"Arogga: {sitemap_url} → {len(urls)} total URLs so far")
            except Exception as e:
                logger.debug(f"Arogga: sitemap {sitemap_url} failed: {e}")

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
        page_text = page.text if hasattr(page, "text") else ""

        # Primary: JSON-LD Product schema (always present on Arogga App Router pages)
        jsonld = self.extract_jsonld(page)
        jsonld_drug: Drug | None = None
        for ld in jsonld:
            if ld.get("@type") == "Product":
                jsonld_drug = self._parse_jsonld(ld, url)
                break

        # Secondary: extract richer fields from RSC streaming payload
        # Arogga embeds product data as JSON inside self.__next_f.push() calls
        rsc_product = self._extract_rsc_product(page_text)
        if rsc_product and jsonld_drug:
            # Merge RSC fields into JSON-LD parsed drug
            if rsc_product.get("generic_name") and not jsonld_drug.generic_name:
                jsonld_drug.generic_name = rsc_product["generic_name"]
            if rsc_product.get("dosage_form") and not jsonld_drug.dosage_form:
                jsonld_drug.dosage_form = rsc_product["dosage_form"]
            if rsc_product.get("strength") and not jsonld_drug.strength:
                jsonld_drug.strength = rsc_product["strength"]
            if rsc_product.get("manufacturer") and not jsonld_drug.manufacturer:
                jsonld_drug.manufacturer = Manufacturer(
                    name=rsc_product["manufacturer"], country="Bangladesh"
                )
            if rsc_product.get("source_id") and not jsonld_drug.source_id:
                jsonld_drug.source_id = rsc_product["source_id"]
            return jsonld_drug

        if jsonld_drug:
            return jsonld_drug

        # Tertiary: __NEXT_DATA__ (legacy Next.js pages)
        next_data = self._extract_next_data(page)
        if next_data:
            props = next_data.get("props", {}).get("pageProps", {})
            product = props.get("product") or props.get("medicine") or props.get("data", {})
            if isinstance(product, dict) and product:
                return self._parse_product(product, url)

        # Fallback: HTML
        return self._parse_html(page, url, jsonld)

    def _extract_rsc_product(self, page_text: str) -> dict | None:
        """
        Arogga App Router embeds product data in RSC streaming payload:
        self.__next_f.push([1, "...{\"p_name\":\"...\",\"p_form\":\"...\"}..."])
        Extract p_name, p_form, p_strength, generic_name, manufacturer etc.
        """
        # Look for product variant objects that have p_name + p_form
        matches = re.findall(
            r'\{[^{}]*"p_name"\s*:\s*"([^"]+)"[^{}]*"p_form"\s*:\s*"([^"]*?)"[^{}]*\}',
            page_text,
        )
        if not matches:
            return None

        # Use the first match as the primary product variant
        p_name, p_form = matches[0]

        # Try to find strength in the same RSC block
        strength_matches = re.findall(
            r'"p_strength"\s*:\s*"([^"]*?)"', page_text
        )
        strength = strength_matches[0] if strength_matches else ""

        # Try to find generic_name in RSC payload
        generic_matches = re.findall(
            r'"generic_name"\s*:\s*"([^"]+?)"', page_text
        )
        generic_name = generic_matches[0] if generic_matches else ""

        # Try to find product id
        id_matches = re.findall(r'"p_id"\s*:\s*(\d+)', page_text)
        source_id = id_matches[0] if id_matches else ""

        # Try to find manufacturer from brand block
        mfr_matches = re.findall(
            r'"brand_name"\s*:\s*"([^"]+?)"', page_text
        )
        manufacturer = mfr_matches[0] if mfr_matches else ""

        return {
            "p_name": p_name,
            "dosage_form": p_form,
            "strength": strength,
            "generic_name": generic_name,
            "source_id": source_id,
            "manufacturer": manufacturer,
        }

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

        # Arogga JSON-LD Product name format: "{BrandName} {GenericName} {Form} {Strength}"
        # e.g. "3-Geocef Cefixime Powder for Suspension 200mg/5ml"
        full_name = ld.get("name") or ""

        # Price from offers
        price = None
        price_raw = offers.get("price")
        if price_raw:
            try:
                price = DrugPrice(
                    amount=float(price_raw),
                    currency=offers.get("priceCurrency", "BDT"),
                )
            except (ValueError, TypeError):
                pass

        # Multiple price tiers from offers array
        prices = []
        if isinstance(ld.get("offers"), list):
            for o in ld["offers"]:
                try:
                    prices.append(DrugPrice(
                        amount=float(o["price"]),
                        currency=o.get("priceCurrency", "BDT"),
                        unit=o.get("name", ""),
                    ))
                except (KeyError, ValueError, TypeError):
                    pass

        # Availability
        availability = offers.get("availability", "")

        return Drug(
            source="arogga",
            source_url=url,
            brand_name=full_name,
            description=ld.get("description"),
            image_url=ld.get("image") if isinstance(ld.get("image"), str) else (
                ld["image"].get("url") if isinstance(ld.get("image"), dict) else None
            ),
            price=price or (prices[0] if prices else None),
            prices=prices,
            categories=[
                c.get("name", "") for c in ld.get("category", [])
                if isinstance(c, dict)
            ] if isinstance(ld.get("category"), list) else (
                [ld["category"]] if isinstance(ld.get("category"), str) else []
            ),
            extra={
                "jsonld": ld,
                "sku": ld.get("sku"),
                "gtin": ld.get("gtin"),
                "availability": availability,
                "offers_count": len(prices),
            },
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
