"""Arogga scraper - arogga.com - 32k+ medicines, online pharmacy.

Structure (verified 2026-05):
- Next.js 13+ App Router (no __NEXT_DATA__; RSC streaming)
- Sitemaps at /sitemap.xml (index) → /sitemap/0.xml … /sitemap/19.xml (3k URLs each)
- Product URLs: /product/{id}/{slug}
- Product data exposed in JSON-LD <script type="application/ld+json">
- RSC payload in self.__next_f.push() — parsed for extra fields
- p_name, p_form, p_strength, generic_name present in RSC blocks

Fix (2026-05): Added direct REST API discovery as primary method.
Arogga exposes a paginated JSON API used by their mobile/web app.
This is faster and more reliable than sitemap+stealth scraping.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator

import httpx
import orjson
from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)

# Known Arogga REST API endpoints (discovered via network inspection)
_API_CANDIDATES = [
    "https://www.arogga.com/api/v1/medicines",
    "https://www.arogga.com/api/medicines",
    "https://www.arogga.com/api/products",
    "https://www.arogga.com/api/v1/products",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.arogga.com/",
    "Origin": "https://www.arogga.com",
}


class AroggaScraper(BaseScrapingScraper):
    name = "arogga"
    base_url = "https://www.arogga.com"
    rate_limit = 0.5
    use_stealth = True

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Strategy 1: Try REST API (fastest, most complete)
        api_drugs = await self._try_api_scrape()
        if api_drugs:
            logger.info(f"Arogga: API collected {len(api_drugs)} drugs")
            for drug in api_drugs:
                yield drug
            return

        # Strategy 2: Sitemap → product pages
        logger.info("Arogga: API failed, falling back to sitemap scrape")
        urls = await self._get_product_urls_from_sitemaps()
        logger.info(f"Arogga: found {len(urls)} product URLs from sitemaps")

        if not urls:
            urls = await self._get_product_urls_from_listing()
            logger.info(f"Arogga: found {len(urls)} product URLs from listing")

        for url in urls:
            try:
                drug = await self._scrape_product_page(url)
                if drug and self._is_medicine(drug):
                    yield drug
            except Exception as e:
                logger.warning(f"Arogga: error scraping {url}: {e}")

    # ------------------------------------------------------------------ #
    # Strategy 1: REST API                                                 #
    # ------------------------------------------------------------------ #

    async def _try_api_scrape(self) -> list[Drug]:
        """Try known API endpoints; return all drugs if any endpoint works."""
        async with httpx.AsyncClient(
            headers=_HEADERS,
            follow_redirects=True,
            timeout=20,
        ) as client:
            for endpoint in _API_CANDIDATES:
                try:
                    drugs = await self._paginate_api(client, endpoint)
                    if drugs:
                        logger.info(f"Arogga: API endpoint works: {endpoint}")
                        return drugs
                except Exception as e:
                    logger.debug(f"Arogga: API {endpoint} failed: {e}")
        return []

    async def _paginate_api(
        self, client: httpx.AsyncClient, endpoint: str
    ) -> list[Drug]:
        drugs: list[Drug] = []
        page = 1

        # Probe first page
        r = await client.get(endpoint, params={"page": 1, "per_page": 100})
        if r.status_code != 200:
            return []
        data = r.json()
        items = self._extract_items(data)
        if not items:
            return []

        while True:
            for item in items:
                slug = item.get("slug") or item.get("alias") or ""
                pid = item.get("id") or item.get("p_id") or ""
                url = f"{self.base_url}/product/{pid}/{slug}" if pid else self.base_url
                drug = self._parse_api_item(item, url)
                if drug:
                    drugs.append(drug)

            # Next page
            page += 1
            await asyncio.sleep(self.rate_limit)
            r = await client.get(endpoint, params={"page": page, "per_page": 100})
            if r.status_code != 200:
                break
            data = r.json()
            items = self._extract_items(data)
            if not items:
                break

            if len(drugs) % 1000 == 0:
                logger.info(f"Arogga API: collected {len(drugs)} so far...")

        return drugs

    @staticmethod
    def _extract_items(data: dict | list) -> list:
        if isinstance(data, list):
            return data
        for key in ("data", "products", "medicines", "items", "results"):
            v = data.get(key)
            if isinstance(v, list) and v:
                return v
        return []

    def _parse_api_item(self, item: dict, url: str) -> Drug | None:
        name = (
            item.get("p_name")
            or item.get("name")
            or item.get("title")
            or item.get("brand_name")
        )
        if not name:
            return None

        # Price
        price_val = (
            item.get("price")
            or item.get("mrp")
            or item.get("unit_price")
            or item.get("selling_price")
        )
        price: DrugPrice | None = None
        if price_val:
            try:
                price = DrugPrice(amount=float(price_val), currency="BDT")
            except (ValueError, TypeError):
                pass

        mfr_raw = item.get("manufacturer") or item.get("company") or item.get("brand_name_en", "")
        mfr = (
            Manufacturer(name=mfr_raw, country="Bangladesh")
            if mfr_raw and isinstance(mfr_raw, str)
            else None
        )

        return Drug(
            source="arogga",
            source_url=url,
            source_id=str(item.get("p_id") or item.get("id") or ""),
            brand_name=name,
            generic_name=(
                item.get("generic_name")
                or item.get("generic")
                or item.get("molecule")
                or item.get("p_generic_name")
            ),
            dosage_form=item.get("p_form") or item.get("dosage_form") or item.get("form"),
            strength=item.get("p_strength") or item.get("strength") or item.get("dose"),
            manufacturer=mfr,
            price=price,
            description=item.get("description") or item.get("p_description"),
            image_url=item.get("image") or item.get("thumbnail") or item.get("p_image"),
            categories=(
                [item["category"]]
                if isinstance(item.get("category"), str)
                else [
                    c.get("name", "")
                    for c in item.get("category", [])
                    if isinstance(c, dict)
                ]
            ),
            extra={
                k: v
                for k, v in item.items()
                if k
                not in (
                    "p_name", "name", "title", "brand_name",
                    "generic_name", "generic", "molecule", "p_generic_name",
                    "p_form", "dosage_form", "form",
                    "p_strength", "strength", "dose",
                    "manufacturer", "company",
                    "price", "mrp", "unit_price", "selling_price",
                    "description", "p_description",
                    "image", "thumbnail", "p_image",
                    "category", "slug", "id", "p_id",
                )
            },
        )

    @staticmethod
    def _is_medicine(drug) -> bool:
        """
        Filter out non-medicine products (cosmetics, food, household items).
        Arogga sells everything — we only want actual drugs/medicines.
        """
        # Keep if has generic name or pharma-related therapeutic class
        if drug.generic_name:
            return True
        # Skip obvious non-medicine categories
        skip_categories = {
            'home_care', 'baby_care', 'personal_care', 'beauty', 'food',
            'grocery', 'cosmetics', 'household', 'toy', 'electronics',
            'perfume', 'fragrance', 'clothing', 'stationery',
        }
        for cat in (drug.categories or []):
            if cat.lower().replace(' ', '_') in skip_categories:
                return False
        # Skip if brand name contains strong non-medicine keywords
        non_med = [
            'detergent', 'soap bar', 'shampoo', 'conditioner', 'perfume', 'cologne',
            'deodorant', 'lipstick', 'mascara', 'foundation', 'blush', 'eyeliner',
            'nail polish', 'hair color', 'hair dye', 'face wash', 'body lotion',
            'condom', 'sanitary', 'diaper', 'baby wipes', 'tissue', 'candy',
            'chocolate', 'biscuit', 'juice', 'energy drink', 'protein powder',
            'marshmallow', 'haribo', 'toy', 'remote control',
        ]
        name_lower = (drug.brand_name or '').lower()
        for kw in non_med:
            if kw in name_lower:
                return False
        # Keep everything else (medicines, supplements, medical devices)
        return True

    # ------------------------------------------------------------------ #
    # Strategy 2: Sitemap                                                  #
    # ------------------------------------------------------------------ #

    async def _get_product_urls_from_sitemaps(self) -> list[str]:
        urls: set[str] = set()

        # Fetch sitemap index
        sitemap_paths: list[str] = []
        try:
            async with httpx.AsyncClient(
                headers=_HEADERS, follow_redirects=True, timeout=15
            ) as client:
                r = await client.get(f"{self.base_url}/sitemap.xml")
                discovered = re.findall(
                    r"<loc>(https?://[^<]+/sitemap/[^<]+\.xml)</loc>", r.text
                )
                sitemap_paths = [
                    u for u in discovered if re.search(r"/sitemap/\d+\.xml", u)
                ]
                logger.info(f"Arogga: found {len(sitemap_paths)} product sitemaps")
        except Exception:
            sitemap_paths = [f"{self.base_url}/sitemap/{i}.xml" for i in range(20)]

        async with httpx.AsyncClient(
            headers=_HEADERS, follow_redirects=True, timeout=15
        ) as client:
            for sitemap_url in sitemap_paths:
                try:
                    r = await client.get(sitemap_url)
                    for match in re.findall(
                        r"<loc>(https?://[^<]+/product/[^<]+)</loc>", r.text
                    ):
                        urls.add(match)
                    logger.debug(f"Arogga: {sitemap_url} → {len(urls)} total URLs")
                except Exception as e:
                    logger.debug(f"Arogga: sitemap {sitemap_url} failed: {e}")

        return list(urls)

    async def _get_product_urls_from_listing(self) -> list[str]:
        urls: set[str] = set()
        for page_num in range(1, 500):
            try:
                page = await self.fetch_page(
                    f"{self.base_url}/medicine?page={page_num}"
                )
                found = 0
                for link in page.css('a[href*="/product/"]'):
                    href = link.attrib.get("href", "")
                    if href:
                        full = (
                            href
                            if href.startswith("http")
                            else f"{self.base_url}{href}"
                        )
                        urls.add(full)
                        found += 1

                if found == 0:
                    next_data = self._extract_next_data(page)
                    if next_data:
                        props = (
                            next_data.get("props", {}).get("pageProps", {})
                        )
                        products = props.get(
                            "products",
                            props.get("medicines", props.get("data", [])),
                        )
                        if isinstance(products, list):
                            for p in products:
                                pid = p.get("id") or p.get("_id") or ""
                                slug = p.get("slug") or p.get("alias") or ""
                                if pid:
                                    urls.add(
                                        f"{self.base_url}/product/{pid}/{slug}"
                                    )
                                    found += 1

                if found == 0:
                    break
            except Exception:
                break

        return list(urls)

    # ------------------------------------------------------------------ #
    # Strategy 2: Product page scraping                                    #
    # ------------------------------------------------------------------ #

    async def _scrape_product_page(self, url: str) -> Drug | None:
        # Fast path: plain httpx with good headers
        try:
            async with httpx.AsyncClient(
                headers=_HEADERS, follow_redirects=True, timeout=15
            ) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    drug = self._parse_page_text(r.text, url)
                    if drug:
                        return drug
        except Exception:
            pass

        # Slow path: stealth browser
        page = await self.fetch_page(url)
        page_text = page.text if hasattr(page, "text") else ""
        return self._parse_page_text(page_text, url)

    def _parse_page_text(self, html: str, url: str) -> Drug | None:
        import json

        # 1) JSON-LD Product
        for match in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>',
            html,
            re.IGNORECASE,
        ):
            try:
                ld = json.loads(match.group(1))
                if isinstance(ld, dict) and ld.get("@type") == "Product":
                    drug = self._parse_jsonld(ld, url)
                    # Enrich from RSC
                    rsc = self._extract_rsc_product(html)
                    if rsc and drug:
                        if rsc.get("generic_name") and not drug.generic_name:
                            drug.generic_name = rsc["generic_name"]
                        if rsc.get("dosage_form") and not drug.dosage_form:
                            drug.dosage_form = rsc["dosage_form"]
                        if rsc.get("strength") and not drug.strength:
                            drug.strength = rsc["strength"]
                        if rsc.get("manufacturer") and not drug.manufacturer:
                            drug.manufacturer = Manufacturer(
                                name=rsc["manufacturer"], country="Bangladesh"
                            )
                        if rsc.get("source_id") and not drug.source_id:
                            drug.source_id = rsc["source_id"]
                    return drug
            except Exception:
                continue

        # 2) __NEXT_DATA__
        nd_match = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>([\s\S]+?)</script>', html
        )
        if nd_match:
            try:
                nd = json.loads(nd_match.group(1))
                props = nd.get("props", {}).get("pageProps", {})
                product = (
                    props.get("product")
                    or props.get("medicine")
                    or props.get("data", {})
                )
                if isinstance(product, dict) and product:
                    return self._parse_api_item(product, url)
            except Exception:
                pass

        return None

    def _extract_rsc_product(self, page_text: str) -> dict | None:
        matches = re.findall(
            r'\{[^{}]*"p_name"\s*:\s*"([^"]+)"[^{}]*"p_form"\s*:\s*"([^"]*?)"[^{}]*\}',
            page_text,
        )
        if not matches:
            return None

        p_name, p_form = matches[0]
        strength_m = re.findall(r'"p_strength"\s*:\s*"([^"]*?)"', page_text)
        generic_m = re.findall(r'"generic_name"\s*:\s*"([^"]+?)"', page_text)
        id_m = re.findall(r'"p_id"\s*:\s*(\d+)', page_text)
        mfr_m = re.findall(r'"brand_name"\s*:\s*"([^"]+?)"', page_text)

        return {
            "p_name": p_name,
            "dosage_form": p_form,
            "strength": strength_m[0] if strength_m else "",
            "generic_name": generic_m[0] if generic_m else "",
            "source_id": id_m[0] if id_m else "",
            "manufacturer": mfr_m[0] if mfr_m else "",
        }

    def _extract_next_data(self, page) -> dict | None:
        script = page.css_first('script#__NEXT_DATA__')
        if script and script.text:
            try:
                return orjson.loads(script.text)
            except Exception:
                pass
        return None

    def _parse_jsonld(self, ld: dict, url: str) -> Drug:
        offers = ld.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        full_name = ld.get("name") or ""

        price: DrugPrice | None = None
        price_raw = offers.get("price")
        if price_raw:
            try:
                price = DrugPrice(
                    amount=float(price_raw),
                    currency=offers.get("priceCurrency", "BDT"),
                )
            except (ValueError, TypeError):
                pass

        prices: list[DrugPrice] = []
        if isinstance(ld.get("offers"), list):
            for o in ld["offers"]:
                try:
                    prices.append(
                        DrugPrice(
                            amount=float(o["price"]),
                            currency=o.get("priceCurrency", "BDT"),
                            unit=o.get("name", ""),
                        )
                    )
                except (KeyError, ValueError, TypeError):
                    pass

        return Drug(
            source="arogga",
            source_url=url,
            brand_name=full_name,
            description=ld.get("description"),
            image_url=(
                ld.get("image")
                if isinstance(ld.get("image"), str)
                else (
                    ld["image"].get("url")
                    if isinstance(ld.get("image"), dict)
                    else None
                )
            ),
            price=price or (prices[0] if prices else None),
            prices=prices,
            categories=(
                [c.get("name", "") for c in ld.get("category", []) if isinstance(c, dict)]
                if isinstance(ld.get("category"), list)
                else ([ld["category"]] if isinstance(ld.get("category"), str) else [])
            ),
            extra={
                "jsonld": ld,
                "sku": ld.get("sku"),
                "gtin": ld.get("gtin"),
                "availability": offers.get("availability", ""),
                "offers_count": len(prices),
            },
        )
