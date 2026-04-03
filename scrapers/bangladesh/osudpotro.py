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
        urls = set()

        # Try to get category list first
        try:
            page = await self.fetch_page(self.base_url)
            # Extract __NEXT_DATA__ from homepage for category list
            next_data = self._extract_next_data(page)
            if next_data:
                # Look for categories in pageProps
                props = next_data.get("props", {}).get("pageProps", {})
                categories = props.get("categories", props.get("allCategories", []))
                if isinstance(categories, list):
                    for cat in categories:
                        alias = cat.get("alias") or cat.get("slug") or cat.get("_id", "")
                        if alias:
                            # Paginate through category
                            for pg in range(1, 200):
                                try:
                                    cat_page = await self.fetch_page(
                                        f"{self.base_url}/category/{alias}?page={pg}"
                                    )
                                    cat_data = self._extract_next_data(cat_page)
                                    if cat_data:
                                        cat_props = cat_data.get("props", {}).get("pageProps", {})
                                        products = cat_props.get("products", cat_props.get("items", []))
                                        if not products:
                                            break
                                        for p in products:
                                            slug = p.get("alias") or p.get("slug") or p.get("_id", "")
                                            if slug:
                                                urls.add(f"{self.base_url}/{slug}")
                                    else:
                                        # Fallback: look for product links in HTML
                                        found = 0
                                        for link in cat_page.css('a[href]'):
                                            href = link.attrib.get("href", "")
                                            if href and href.startswith("/") and not href.startswith("/category"):
                                                full = f"{self.base_url}{href}"
                                                urls.add(full)
                                                found += 1
                                        if found == 0:
                                            break
                                except Exception:
                                    break
        except Exception as e:
            logger.warning(f"Osudpotro: category discovery failed: {e}")

        # Fallback: paginated product listing
        if not urls:
            for pg in range(1, 500):
                try:
                    page = await self.fetch_page(f"{self.base_url}/medicines?page={pg}")
                    found = 0
                    for link in page.css('a[href]'):
                        href = link.attrib.get("href", "")
                        if href and href.startswith("/") and len(href) > 2 and not href.startswith(("/category", "/medicines", "/cart", "/account")):
                            urls.add(f"{self.base_url}{href}")
                            found += 1
                    if found == 0:
                        break
                except Exception:
                    break

        return list(urls)

    async def _scrape_product_page(self, url: str) -> Drug | None:
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
