"""Osudpotro scraper - osudpotro.com - 7 lakh+ items.

Architecture (verified 2026-05):
- Next.js CSR app — all product data fetched client-side via REST API
- API base: https://api.osudpotro.com/api/v1/
- Auth: POST /users/guest_login → JWT token (long-lived, 9999d)
- Product data: GET /item/get_by_alias?alias={slug}
- No bulk list endpoint exposed publicly
- Product slugs discoverable via:
  1. homeScreenData category_data (110+ category aliases in __NEXT_DATA__)
  2. GET /home/get_featured_items (7 curated items)
  3. Medex/BDMedex brand name → lowercase slug heuristic

Fix (2026-05):
  - Replaced broken category/httpx approach with REST API + guest_login
  - URL discovery uses homeScreenData categories + Playwright-based category scraping
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from typing import AsyncIterator

import httpx
import orjson
from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)

_API_BASE = "https://api.osudpotro.com/api/v1"
_SITE_BASE = "https://osudpotro.com"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://osudpotro.com",
    "Referer": "https://osudpotro.com/",
}


class OsudpotroScraper(BaseScrapingScraper):
    name = "osudpotro"
    base_url = _SITE_BASE
    rate_limit = 0.3
    use_stealth = True
    use_dynamic = True

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Step 1: Get guest token
        token = await self._get_guest_token()
        if not token:
            logger.error("Osudpotro: failed to get guest token, aborting")
            return

        # Step 2: Collect product slugs
        aliases = await self._collect_aliases(token)
        logger.info(f"Osudpotro: collected {len(aliases)} product aliases")

        # Step 3: Fetch each product via API
        auth_headers = {**_HEADERS, "Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(
            headers=auth_headers, follow_redirects=True, timeout=20
        ) as client:
            for i, alias in enumerate(aliases):
                try:
                    drug = await self._fetch_by_alias(client, alias)
                    if drug:
                        yield drug
                except Exception as e:
                    logger.warning(f"Osudpotro: error fetching {alias}: {e}")

                if (i + 1) % 500 == 0:
                    logger.info(f"Osudpotro: processed {i + 1}/{len(aliases)}")
                await asyncio.sleep(self.rate_limit)

    # ------------------------------------------------------------------ #
    # Auth                                                                 #
    # ------------------------------------------------------------------ #

    async def _get_guest_token(self) -> str | None:
        try:
            async with httpx.AsyncClient(headers=_HEADERS, follow_redirects=True, timeout=15) as c:
                r = await c.post(f"{_API_BASE}/users/guest_login", json={})
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status"):
                        return data["data"]["token"]
        except Exception as e:
            logger.error(f"Osudpotro: guest_login failed: {e}")
        return None

    # ------------------------------------------------------------------ #
    # Alias/Slug Discovery                                                 #
    # ------------------------------------------------------------------ #

    async def _collect_aliases(self, token: str) -> list[str]:
        """Collect product aliases from multiple sources."""
        aliases: dict[str, None] = {}
        auth_headers = {**_HEADERS, "Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(
            headers=auth_headers, follow_redirects=True, timeout=20
        ) as client:
            # Source 1: Featured items (7 curated)
            try:
                r = await client.get(f"{_API_BASE}/home/get_featured_items")
                data = r.json()
                for item in data.get("data", []) or []:
                    a = item.get("alias") or item.get("slug")
                    if a:
                        aliases[a] = None
                logger.debug(f"Osudpotro: featured items gave {len(aliases)} aliases")
            except Exception:
                pass

            # Source 2: homeScreenData category slugs from site __NEXT_DATA__
            # These category aliases can be used to discover product slugs via Playwright
            category_aliases = await self._get_category_aliases()
            logger.info(f"Osudpotro: found {len(category_aliases)} category aliases")

            # Source 3: Playwright-rendered category pages (intercept API calls)
            # For each category, use Playwright to load the page and intercept
            # the actual API response for product listings
            if category_aliases:
                category_products = await self._scrape_categories_playwright(
                    category_aliases, token
                )
                for a in category_products:
                    aliases[a] = None
                logger.info(f"Osudpotro: category scraping gave {len(aliases)} total aliases")

        return list(aliases.keys())

    async def _get_category_aliases(self) -> list[str]:
        """Extract category aliases from the site's __NEXT_DATA__."""
        cat_aliases: list[str] = []
        try:
            async with httpx.AsyncClient(
                headers={k: v for k, v in _HEADERS.items() if k != "Accept"},
                follow_redirects=True, timeout=15
            ) as client:
                r = await client.get(_SITE_BASE)
                nd_match = re.search(
                    r'<script id="__NEXT_DATA__"[^>]*>([\s\S]+?)</script>', r.text
                )
                if nd_match:
                    nd = orjson.loads(nd_match.group(1))
                    home_data = nd.get("props", {}).get("pageProps", {}).get("homeScreenData", [])
                    for section in home_data or []:
                        for cat in section.get("category_data", []) or []:
                            alias = cat.get("cat_alias") or cat.get("alias")
                            if alias and alias not in cat_aliases:
                                cat_aliases.append(alias)
        except Exception as e:
            logger.warning(f"Osudpotro: category alias discovery failed: {e}")
        return cat_aliases

    async def _scrape_categories_playwright(
        self, category_aliases: list[str], token: str
    ) -> list[str]:
        """Use Playwright to load category pages and intercept product listing API calls."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Osudpotro: playwright not installed, skipping category scrape")
            return []

        aliases: dict[str, None] = {}

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)

                # Intercept all API responses from api.osudpotro.com
                async def on_response(response):
                    url = response.url
                    if "api.osudpotro.com" in url and "item" in url.lower():
                        try:
                            body = await response.text()
                            data = orjson.loads(body)
                            if data.get("status"):
                                items = data.get("data", {})
                                if isinstance(items, list):
                                    for item in items:
                                        a = item.get("alias") or item.get("slug")
                                        if a:
                                            aliases[a] = None
                                elif isinstance(items, dict):
                                    a = items.get("alias") or items.get("slug")
                                    if a:
                                        aliases[a] = None
                        except Exception:
                            pass

                page = await browser.new_page()
                page.on("response", on_response)

                for alias in category_aliases[:30]:  # limit to avoid timeout
                    try:
                        url = f"{_SITE_BASE}/category/{alias}"
                        await page.goto(url, wait_until="networkidle", timeout=20000)
                        await page.wait_for_timeout(2000)
                    except Exception:
                        pass

                await browser.close()
        except Exception as e:
            logger.warning(f"Osudpotro: Playwright category scrape failed: {e}")

        return list(aliases.keys())

    # ------------------------------------------------------------------ #
    # Product fetching                                                     #
    # ------------------------------------------------------------------ #

    async def _fetch_by_alias(
        self, client: httpx.AsyncClient, alias: str
    ) -> Drug | None:
        r = await client.get(
            f"{_API_BASE}/item/get_by_alias", params={"alias": alias}
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if not data.get("status"):
            return None
        item = data.get("data")
        if not isinstance(item, dict):
            return None
        url = f"{_SITE_BASE}/{alias}"
        return self._parse_product(item, url, alias)

    # ------------------------------------------------------------------ #
    # Parsers                                                              #
    # ------------------------------------------------------------------ #

    def _parse_product(self, item: dict, url: str, alias: str = "") -> Drug | None:
        name = item.get("item_name") or item.get("name") or item.get("title")
        if not name:
            return None

        # Pricing from inventory tiers
        prices: list[DrugPrice] = []
        for inv in item.get("inventory") or []:
            pv = inv.get("sell_price") or inv.get("price") or inv.get("mrp")
            if pv:
                try:
                    prices.append(
                        DrugPrice(
                            amount=float(pv),
                            currency="BDT",
                            unit=inv.get("unit") or inv.get("sku_type", ""),
                            pack_size=inv.get("pack_size") or inv.get("quantity"),
                        )
                    )
                except (ValueError, TypeError):
                    pass

        price: DrugPrice | None = prices[0] if prices else None
        if not price:
            pv = item.get("sell_price") or item.get("price") or item.get("mrp")
            if pv:
                try:
                    price = DrugPrice(amount=float(pv), currency="BDT")
                except (ValueError, TypeError):
                    pass

        # Manufacturers
        manufacturers: list[Manufacturer] = []
        for m in item.get("manufacturers") or []:
            if isinstance(m, dict):
                manufacturers.append(
                    Manufacturer(name=m.get("name", ""), country="Bangladesh")
                )
            elif isinstance(m, str):
                manufacturers.append(Manufacturer(name=m, country="Bangladesh"))

        # Description: URL-encoded HTML
        desc_raw = item.get("item_desc") or item.get("description") or ""
        desc = urllib.parse.unquote(desc_raw) if desc_raw else ""

        # Images
        images = item.get("images") or []
        image_url = None
        if images and isinstance(images[0], dict):
            img = images[0].get("img") or images[0].get("url") or ""
            if img:
                image_url = (
                    img if img.startswith("http")
                    else f"https://cdn.osudpotro.com/{img}"
                )

        # generic_name may come as a list from the API
        raw_generic = item.get("generic_name") or item.get("generic")
        if isinstance(raw_generic, list):
            raw_generic = ", ".join(str(g) for g in raw_generic if g)

        return Drug(
            source="osudpotro",
            source_url=url,
            source_id=str(item.get("_id") or item.get("id") or ""),
            brand_name=name,
            generic_name=raw_generic or None,
            dosage_form=item.get("sku_type") or item.get("dosage_form") or item.get("form"),
            strength=item.get("strength") or item.get("dose"),
            manufacturer=manufacturers[0] if manufacturers else None,
            manufacturers=manufacturers,
            price=price,
            prices=prices,
            description=desc,
            image_url=image_url,
            categories=(
                [item["cat_name"]] if item.get("cat_name") else []
            ),
            extra={
                "alias": alias or item.get("alias"),
                "sku_type": item.get("sku_type"),
                "item_type": item.get("item_type"),
                "cat_id": item.get("cat_id"),
                "cat_name": item.get("cat_name"),
                "inventory": item.get("inventory"),
                "discount": item.get("discount"),
                "is_rx": item.get("is_rx"),
                "in_home_screen": item.get("in_home_screen"),
                "manufacturers_alias": item.get("manufacturers_alias"),
                "item_desc_pdf": item.get("item_desc_pdf"),
            },
        )
