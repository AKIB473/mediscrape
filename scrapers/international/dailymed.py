"""DailyMed scraper - Current FDA-approved drug labeling. Free REST API v2.

Note: The /spls/{setid}.json detail endpoint returns 415. Only XML works for
full SPL details. Sub-endpoints (ndcs.json, packaging.json) work fine with JSON.
We use the drugnames endpoint + NDC sub-endpoints to get structured data.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from models.drug import Drug, Manufacturer
from scrapers.base import BaseAPIScraper

logger = logging.getLogger(__name__)

BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"


class DailyMedScraper(BaseAPIScraper):
    name = "dailymed"
    base_url = BASE
    rate_limit = 0.3

    async def scrape_all(self) -> AsyncIterator[Drug]:
        page = 1
        pagesize = 100

        while True:
            data = await self.api_get(
                f"{BASE}/spls.json",
                params={"page": page, "pagesize": pagesize},
            )
            spls = data.get("data", [])
            if not spls:
                break

            for spl in spls:
                set_id = spl.get("setid")
                if not set_id:
                    continue
                try:
                    drug = await self._fetch_spl_detail(set_id, spl)
                    if drug:
                        yield drug
                except Exception as e:
                    logger.warning(f"DailyMed: error fetching {set_id}: {e}")

            metadata = data.get("metadata", {})
            total_pages = metadata.get("total_pages", 0)
            if page >= total_pages:
                break
            page += 1

    async def _fetch_spl_detail(self, set_id: str, spl_summary: dict) -> Drug | None:
        # Get NDCs (works with .json)
        ndc_data = await self.api_get(f"{BASE}/spls/{set_id}/ndcs.json")
        ndc_info = ndc_data.get("data", {})
        ndcs = []
        ndc_list = ndc_info.get("ndcs", [])
        if isinstance(ndc_list, list):
            ndcs = [n.get("ndc") if isinstance(n, dict) else n for n in ndc_list]

        title = ndc_info.get("title", spl_summary.get("title", ""))
        published = ndc_info.get("published_date", spl_summary.get("published_date"))

        # Get packaging info (works with .json)
        packages = []
        try:
            packaging = await self.api_get(f"{BASE}/spls/{set_id}/packaging.json")
            packages = packaging.get("data", [])
        except Exception:
            pass

        # Parse brand and generic from title
        # DailyMed title format: "BRAND NAME (GENERIC) FORM [MANUFACTURER]"
        brand_name = None
        generic_name = None
        manufacturer = None

        if title:
            # Extract manufacturer from brackets
            if "[" in title and "]" in title:
                mfr_start = title.rindex("[")
                mfr_end = title.rindex("]")
                mfr_name = title[mfr_start + 1:mfr_end].strip()
                manufacturer = Manufacturer(name=mfr_name)
                title_clean = title[:mfr_start].strip()
            else:
                title_clean = title

            # Extract generic from parentheses
            if "(" in title_clean and ")" in title_clean:
                paren_start = title_clean.index("(")
                paren_end = title_clean.index(")")
                generic_name = title_clean[paren_start + 1:paren_end].strip()
                brand_name = title_clean[:paren_start].strip()
            else:
                brand_name = title_clean

        if not brand_name and not generic_name:
            return None

        return Drug(
            source="dailymed",
            source_url=f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}",
            source_id=set_id,
            brand_name=brand_name,
            generic_name=generic_name,
            manufacturer=manufacturer,
            ndc=ndcs,
            description=title,
            approval_date=published,
            extra={
                "spl_version": ndc_info.get("spl_version"),
                "title": title,
                "packaging": packages,
                "document_type": spl_summary.get("document_type"),
            },
        )
