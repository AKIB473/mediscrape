"""Osudpotro scraper - osudpotro.com - 7 lakh+ items.

Structure (from research):
- Next.js app with __NEXT_DATA__ JSON containing full product data
- MongoDB documents with: item_name, generic_name, manufacturers, sku_type,
  inventory (pricing tiers), item_desc (clinical HTML), alternative_items, seo_* fields
- Product URLs: /napa, /sergel-20mg (simple aliases)
- Category pages: /category/{alias}?page={n}
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

import orjson
from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class OsudpotroScraper(BaseScrapingScraper):
    name = "osudpotro"
    base_url = "https://osudpotro.com"
    rate_limit = 1.0
    use_stealth = True
    # NOTE: Category pages return HTTP 500 and /medicines has empty pageProps.
    # URL discovery requires Playwright (DynamicFetcher) to render JS.
    # Individual product pages (e.g. /napa) do have __NEXT_DATA__ server-side.
    # URL collection falls back to stealth-rendered category pages.
    use_dynamic = True  # Enable full browser rendering for URL discovery

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Discover product URLs from category pages
        urls = await self._get_product_urls()
        logger.info(f"Osudpotro: found {len(urls)} product URLs")

        for url in urls:
            try:
                drug = await self._scrape_product_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"Osudpotro: error scraping {url}: {e}")

    async def _get_product_urls(self) -> list[str]:
        """
        Osudpotro URL discovery strategy (verified 2026-05):
        1. Homepage __NEXT_DATA__ has Redux initialState but no category list
        2. Individual product pages e.g. /napa have __NEXT_DATA__.props.pageProps.productData
        3. Category pages: /category/{alias}?page={n} paginate with __NEXT_DATA__
        4. Sitemap is JS-rendered (useless for URL extraction)

        Best strategy: scrape category listing pages via httpx (lighter than stealth)
        to collect product slugs, then scrape individual pages with stealth.
        """
        import httpx as _httpx
        import orjson as _orjson

        urls: dict[str, None] = {}

        # Step 1: Get category list via plain httpx (the category listing page
        # renders category names server-side in the initial HTML even without JS)
        category_aliases: list[str] = []
        try:
            async with _httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                follow_redirects=True, timeout=15,
            ) as _c:
                r = await _c.get(self.base_url)
                # Try extracting __NEXT_DATA__ from homepage
                import re as _re
                nd_match = _re.search(
                    r'<script id="__NEXT_DATA__"[^>]*>(\{[\s\S]+?\})</script>', r.text
                )
                if nd_match:
                    nd = _orjson.loads(nd_match.group(1))
                    props = nd.get("props", {}).get("pageProps", {})
                    cats = props.get("categories") or nd.get("props", {}).get("initialState", {}).get("home", {}).get("categories", [])
                    for cat in (cats or []):
                        alias = cat.get("alias") or cat.get("slug")
                        if alias:
                            category_aliases.append(alias)

                # If no categories from homepage, scrape /category page for links
                if not category_aliases:
                    r2 = await _c.get(f"{self.base_url}/category")
                    cat_links = _re.findall(r'/category/([a-z0-9-]+)', r2.text)
                    category_aliases = list(dict.fromkeys(cat_links))  # dedup, preserve order

        except Exception as e:
            logger.warning(f"Osudpotro: category list fetch failed: {e}")

        logger.info(f"Osudpotro: found {len(category_aliases)} categories")

        # Step 2: Paginate each category via plain httpx to collect product slugs
        try:
            async with _httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=True, timeout=15,
            ) as _c:
                import re as _re
                for alias in category_aliases:
                    for pg in range(1, 300):
                        try:
                            r = await _c.get(
                                f"{self.base_url}/category/{alias}",
                                params={"page": pg},
                            )
                            nd_match = _re.search(
                                r'<script id="__NEXT_DATA__"[^>]*>(\{[\s\S]+?\})</script>',
                                r.text,
                            )
                            if not nd_match:
                                break
                            nd = _orjson.loads(nd_match.group(1))
                            cat_props = nd.get("props", {}).get("pageProps", {})
                            products = (
                                cat_props.get("products")
                                or cat_props.get("items")
                                or cat_props.get("data", [])
                            )
                            if not products:
                                break
                            for p in products:
                                slug = p.get("alias") or p.get("slug") or p.get("_id")
                                if slug:
                                    urls[f"{self.base_url}/{slug}"] = None
                        except Exception:
                            break
        except Exception as e:
            logger.warning(f"Osudpotro: category pagination failed: {e}")

        # Step 3: Fallback — stealth/dynamic rendered category pages
        if not urls:
            # homeScreenData has category aliases; use dynamic fetcher to
            # render category pages that require JS (they return 500 to httpx)
            import re as _re
            for alias in ['prescription-medicines', 'otc-medicines', 'treatments-medicine']:
                for pg in range(1, 200):
                    try:
                        cat_page = await self.fetch_page(
                            f"{self.base_url}/category/{alias}?page={pg}"
                        )
                        cat_text = cat_page.text if hasattr(cat_page, 'text') else ''
                        nd_match = _re.search(
                            r'<script id="__NEXT_DATA__"[^>]*>(\{[\s\S]+?\})</script>',
                            cat_text,
                        )
                        products = []
                        if nd_match:
                            nd = _orjson.loads(nd_match.group(1))
                            cat_props = nd.get("props", {}).get("pageProps", {})
                            products = (
                                cat_props.get("products")
                                or cat_props.get("items")
                                or cat_props.get("data", [])
                            ) or []
                        if not products:
                            # Also try extracting slug from rendered page links
                            for link in cat_page.css('a[href]'):
                                href = link.attrib.get('href', '')
                                if href and href.startswith('/') and len(href) > 2 \
                                        and not href.startswith(('/category', '/cart', '/account', '/login')):
                                    urls[f"{self.base_url}{href}"] = None
                            break
                        for p in products:
                            slug = p.get("alias") or p.get("slug") or p.get("_id")
                            if slug:
                                urls[f"{self.base_url}/{slug}"] = None
                    except Exception:
                        break

        logger.info(f"Osudpotro: collected {len(urls)} unique product URLs")
        return list(urls.keys())

    async def _scrape_product_page(self, url: str) -> Drug | None:
        # Try fast httpx first (Osudpotro renders __NEXT_DATA__ server-side)
        import httpx as _httpx, re as _re, orjson as _orjson
        try:
            async with _httpx.AsyncClient(
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=True, timeout=15,
            ) as _c:
                r = await _c.get(url)
                nd_match = _re.search(
                    r'<script id="__NEXT_DATA__"[^>]*>(\{[\s\S]+?\})</script>', r.text
                )
                if nd_match:
                    nd = _orjson.loads(nd_match.group(1))
                    props = nd.get("props", {}).get("pageProps", {})
                    product = (
                        props.get("productData")
                        or props.get("product")
                        or props.get("item")
                        or props.get("data", {})
                    )
                    if isinstance(product, dict) and product:
                        return self._parse_product(product, url)
        except Exception:
            pass

        # Fallback: stealth scraper
        page = await self.fetch_page(url)

        # Primary method: extract __NEXT_DATA__
        next_data = self._extract_next_data(page)
        if next_data:
            props = next_data.get("props", {}).get("pageProps", {})
            product = props.get("product") or props.get("item") or props.get("data", {})
            if isinstance(product, dict) and product:
                return self._parse_product(product, url)

        # Fallback: extract JSON-LD
        jsonld = self.extract_jsonld(page)
        for ld in jsonld:
            if ld.get("@type") == "Product":
                return self._parse_jsonld_product(ld, url)

        # Final fallback: HTML scraping
        return self._parse_html(page, url)

    def _extract_next_data(self, page) -> dict | None:
        script = page.css_first('script#__NEXT_DATA__')
        if script and script.text:
            try:
                return orjson.loads(script.text)
            except Exception:
                pass
        return None

    def _parse_product(self, item: dict, url: str) -> Drug | None:
        name = item.get("item_name") or item.get("name") or item.get("title")
        if not name:
            return None

        # Parse pricing from inventory tiers
        prices = []
        inventory = item.get("inventory", [])
        if isinstance(inventory, list):
            for inv in inventory:
                price_val = inv.get("price") or inv.get("mrp") or inv.get("selling_price")
                if price_val:
                    try:
                        prices.append(DrugPrice(
                            amount=float(price_val),
                            currency="BDT",
                            unit=inv.get("unit") or inv.get("sku_type", ""),
                            pack_size=inv.get("pack_size") or inv.get("quantity"),
                        ))
                    except (ValueError, TypeError):
                        pass

        # Parse price from flat fields
        price = prices[0] if prices else None
        if not price:
            price_val = item.get("price") or item.get("mrp") or item.get("selling_price")
            if price_val:
                try:
                    price = DrugPrice(amount=float(price_val), currency="BDT")
                except (ValueError, TypeError):
                    pass

        # Parse manufacturers
        manufacturers = []
        mfr_data = item.get("manufacturers") or item.get("manufacturer")
        if isinstance(mfr_data, list):
            for m in mfr_data:
                if isinstance(m, dict):
                    manufacturers.append(Manufacturer(name=m.get("name", ""), country="Bangladesh"))
                elif isinstance(m, str):
                    manufacturers.append(Manufacturer(name=m, country="Bangladesh"))
        elif isinstance(mfr_data, str):
            manufacturers.append(Manufacturer(name=mfr_data, country="Bangladesh"))

        # Parse description HTML for clinical data
        desc_html = item.get("item_desc") or item.get("description") or ""

        # Parse alternative items
        alternatives = item.get("alternative_items", [])

        return Drug(
            source="osudpotro",
            source_url=url,
            source_id=str(item.get("_id", item.get("id", ""))),
            brand_name=name,
            generic_name=item.get("generic_name") or item.get("generic") or item.get("molecule"),
            dosage_form=item.get("sku_type") or item.get("dosage_form") or item.get("form"),
            strength=item.get("strength") or item.get("dose"),
            manufacturer=manufacturers[0] if manufacturers else None,
            manufacturers=manufacturers,
            price=price,
            prices=prices,
            description=desc_html,
            image_url=item.get("image") or item.get("thumbnail") or item.get("photo"),
            categories=[item["category"]] if isinstance(item.get("category"), str) else [c.get("name", "") for c in item.get("category", []) if isinstance(c, dict)],
            extra={
                "sku_type": item.get("sku_type"),
                "alias": item.get("alias"),
                "inventory": inventory,
                "alternatives": alternatives,
                "seo_title": item.get("seo_title"),
                "seo_description": item.get("seo_description"),
                "seo_keywords": item.get("seo_keywords"),
                "is_rx": item.get("is_rx"),
                "is_available": item.get("is_available"),
                "stock": item.get("stock"),
                "discount": item.get("discount"),
                "tags": item.get("tags", []),
                "rating": item.get("rating"),
                "reviews_count": item.get("reviews_count"),
            },
        )

    def _parse_jsonld_product(self, ld: dict, url: str) -> Drug:
        offers = ld.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        return Drug(
            source="osudpotro",
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

    def _parse_html(self, page, url: str) -> Drug | None:
        title = _text(page.css_first("h1"))
        if not title:
            return None

        fields = {}
        for row in page.css("tr, .product-detail, .info-row"):
            label = _text(row.css_first("th, .label, dt"))
            value = _text(row.css_first("td, .value, dd"))
            if label and value:
                fields[label.lower().strip().rstrip(":")] = value

        price_text = _text(page.css_first(".price, [class*=price], .product-price"))

        return Drug(
            source="osudpotro",
            source_url=url,
            brand_name=title,
            generic_name=fields.get("generic", fields.get("generic name", "")),
            dosage_form=fields.get("form", fields.get("type", "")),
            strength=fields.get("strength", ""),
            manufacturer=Manufacturer(name=fields["company"], country="Bangladesh") if fields.get("company") else None,
            price=_parse_price(price_text),
            description=_text(page.css_first(".product-description, .description")),
            extra={"fields": fields},
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
