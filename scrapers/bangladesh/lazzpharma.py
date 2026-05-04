"""Lazz Pharma scraper - lazzpharma.com - Online pharmacy."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class LazzPharmaScraper(BaseScrapingScraper):
    name = "lazzpharma"
    base_url = "https://www.lazzpharma.com"
    rate_limit = 1.0
    use_stealth = True

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Try API first
        api_drugs = await self._try_api()
        if api_drugs:
            for drug in api_drugs:
                yield drug
            return

        # HTML scraping
        urls = await self._get_drug_urls()
        logger.info(f"LazzPharma: found {len(urls)} drug URLs")

        for url in urls:
            try:
                drug = await self._scrape_drug_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"LazzPharma: error scraping {url}: {e}")

    async def _try_api(self) -> list[Drug]:
        drugs = []
        api_paths = [
            "/api/products", "/api/medicines", "/api/v1/products",
            "/wp-json/wc/v3/products",  # WooCommerce
            "/wp-json/wp/v2/product",
        ]

        for path in api_paths:
            try:
                page = await self.fetch_page(f"{self.base_url}{path}")
                if page.status == 200:
                    import orjson
                    try:
                        data = orjson.loads(page.text)
                        items = data if isinstance(data, list) else data.get("data", data.get("products", []))
                        if isinstance(items, list) and items:
                            for item in items:
                                drug = self._parse_product(item)
                                if drug:
                                    drugs.append(drug)
                            logger.info(f"LazzPharma: found API at {path}")
                            return drugs
                    except Exception:
                        pass
            except Exception:
                pass
        return drugs

    def _parse_product(self, item: dict) -> Drug | None:
        name = item.get("name") or item.get("title") or item.get("product_name")
        if isinstance(name, dict):
            name = name.get("rendered", "")
        if not name:
            return None

        price_val = item.get("price") or item.get("regular_price") or item.get("mrp")
        price = None
        if price_val:
            try:
                price = DrugPrice(amount=float(price_val), currency="BDT")
            except (ValueError, TypeError):
                pass

        # Extract from attributes if WooCommerce
        attrs = {}
        for attr in item.get("attributes", []):
            attr_name = attr.get("name", "").lower()
            attr_val = ", ".join(attr.get("options", []))
            attrs[attr_name] = attr_val

        return Drug(
            source="lazzpharma",
            source_url=item.get("permalink") or f"{self.base_url}/product/{item.get('slug', '')}",
            source_id=str(item.get("id", "")),
            brand_name=name,
            generic_name=attrs.get("generic") or attrs.get("generic name") or item.get("generic_name"),
            dosage_form=attrs.get("form") or attrs.get("dosage form") or item.get("dosage_form"),
            strength=attrs.get("strength") or item.get("strength"),
            manufacturer=Manufacturer(name=attrs.get("manufacturer") or attrs.get("company", "")) if attrs.get("manufacturer") or attrs.get("company") else None,
            price=price,
            description=item.get("description") or item.get("short_description"),
            image_url=_get_image(item),
            categories=[c.get("name", "") for c in item.get("categories", []) if isinstance(c, dict)],
            extra={
                "sku": item.get("sku"),
                "stock_status": item.get("stock_status"),
                "sale_price": item.get("sale_price"),
                "attributes": attrs,
                "tags": [t.get("name", "") for t in item.get("tags", []) if isinstance(t, dict)],
            },
        )

    async def _get_drug_urls(self) -> list[str]:
        urls = set()

        # Primary: XML sitemap (LazzPharma has /sitemap/product.xml)
        try:
            sitemap_page = await self.fetch_page(f"{self.base_url}/sitemap.xml")
            sitemap_text = sitemap_page.text if hasattr(sitemap_page, "text") else ""
            import re as _re
            # Find product sitemap from index
            product_sitemaps = _re.findall(
                r"<loc>(https?://[^<]+/sitemap/product[^<]*\.xml)</loc>", sitemap_text
            )
            if not product_sitemaps:
                product_sitemaps = _re.findall(
                    r"<loc>(https?://[^<]+sitemap[^<]*\.xml)</loc>", sitemap_text
                )

            for sm_url in product_sitemaps:
                try:
                    sm_page = await self.fetch_page(sm_url)
                    sm_text = sm_page.text if hasattr(sm_page, "text") else ""
                    for loc in _re.findall(r"<loc>(https?://[^<]+/product/[^<]+)</loc>", sm_text):
                        urls.add(loc)
                    logger.info(f"LazzPharma: {sm_url} → {len(urls)} product URLs")
                except Exception as e:
                    logger.warning(f"LazzPharma: sitemap {sm_url} failed: {e}")
        except Exception as e:
            logger.warning(f"LazzPharma: sitemap discovery failed: {e}")

        # Secondary: WooCommerce category/shop pagination (fallback)
        if not urls:
            cat_paths = ["/shop", "/product-category/medicine", "/medicines", "/products"]
            for path in cat_paths:
                try:
                    page = await self.fetch_page(f"{self.base_url}{path}")
                    for link in page.css('a[href*="/product/"]'):
                        href = link.attrib.get("href", "")
                        if href:
                            full = href if href.startswith("http") else f"{self.base_url}{href}"
                            urls.add(full)

                    # Pagination
                    for pg in range(2, 100):
                        try:
                            pg_page = await self.fetch_page(f"{self.base_url}{path}/page/{pg}/")
                            found = 0
                            for link in pg_page.css('a[href*="/product/"]'):
                                href = link.attrib.get("href", "")
                                if href:
                                    full = href if href.startswith("http") else f"{self.base_url}{href}"
                                    urls.add(full)
                                    found += 1
                            if found == 0:
                                break
                        except Exception:
                            break
                except Exception:
                    pass

        return list(urls)

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        # Parse JSON-LD Product schema if present
        for ld in jsonld:
            if ld.get("@type") == "Product":
                return self._parse_jsonld_product(ld, url)

        title = _text(page.css_first("h1, .product_title"))
        if not title:
            return None

        # WooCommerce product page
        price_text = _text(page.css_first(".price, .woocommerce-Price-amount"))
        sku = _text(page.css_first(".sku"))

        # Product attributes table
        fields = {}
        for row in page.css(".woocommerce-product-attributes tr, .shop_attributes tr, tr"):
            label = _text(row.css_first("th, .label"))
            value = _text(row.css_first("td, .value"))
            if label and value:
                fields[label.lower().strip().rstrip(":")] = value

        desc = _text(page.css_first(".woocommerce-product-details__short-description, .product-description, .description"))

        return Drug(
            source="lazzpharma",
            source_url=url,
            brand_name=title,
            generic_name=fields.get("generic", fields.get("generic name", "")),
            dosage_form=fields.get("form", fields.get("dosage form", "")),
            strength=fields.get("strength", ""),
            manufacturer=Manufacturer(name=fields["manufacturer"]) if fields.get("manufacturer") else None,
            price=_parse_price(price_text),
            description=desc,
            extra={"jsonld": jsonld, "sku": sku, "fields": fields},
        )

    def _parse_jsonld_product(self, ld: dict, url: str) -> Drug:
        offers = ld.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        return Drug(
            source="lazzpharma",
            source_url=url,
            brand_name=ld.get("name"),
            description=ld.get("description"),
            image_url=ld.get("image"),
            price=DrugPrice(
                amount=float(offers["price"]),
                currency=offers.get("priceCurrency", "BDT"),
            ) if offers.get("price") else None,
            extra={
                "jsonld": ld,
                "sku": ld.get("sku"),
                "gtin": ld.get("gtin"),
                "mpn": ld.get("mpn"),
                "availability": offers.get("availability"),
            },
        )


def _text(elem) -> str:
    if elem is None:
        return ""
    return elem.text.strip() if hasattr(elem, "text") and elem.text else ""


def _parse_price(text: str) -> DrugPrice | None:
    if not text:
        return None
    nums = re.findall(r"[\d,.]+", text)
    if nums:
        return DrugPrice(amount=float(nums[0].replace(",", "")), currency="BDT", unit=text)
    return None


def _get_image(item: dict) -> str | None:
    images = item.get("images", [])
    if images and isinstance(images[0], dict):
        return images[0].get("src")
    return item.get("image") or item.get("thumbnail")
