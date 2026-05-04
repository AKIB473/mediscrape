"""DGDA scraper - dgda.gov.bd - Official govt drug registration database.

Verified structure (2026-05):
  Primary DB: http://180.211.137.202:9310/Allopathic/
  Tabs:
    ?Generic_List_With_DCC_Number  - generic names + DCC numbers (DataTables)
    ?Medicine_Information          - full drug info table
    ?Trade_Wise_Search             - brand-name search
    ?Generic_Wise_Search           - generic search
    ?Company_Wise_Search           - manufacturer search
    ?Company_Information           - company details

  OtherTMS: http://180.211.137.202:9310/OtherTMS/
    (same structure for herbal/homeopathic/unani)

  Page protection: right-click + F12 disabled via JS (no API auth needed).
  DataTables renders the HTML table server-side, so full data is in the page HTML.
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)

# DGDA internal IP-based database (accessible publicly)
_ALLOPATHIC_BASE = "http://180.211.137.202:9310/Allopathic"
_OTHERTMS_BASE   = "http://180.211.137.202:9310/OtherTMS"

# Canonical DGDA domain (used as source_url prefix)
_CANONICAL_URL = "https://dgda.gov.bd"


class DGDAScraper(BaseScrapingScraper):
    name = "dgda"
    base_url = _ALLOPATHIC_BASE
    rate_limit = 1.5
    use_stealth = False  # Plain HTTP, no JS needed

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # 1. Scrape Medicine_Information table (most complete: brand + generic + company + price)
        count = 0
        async for drug in self._scrape_table(
            url=f"{_ALLOPATHIC_BASE}/?Medicine_Information",
            source_label="dgda-allopathic",
        ):
            yield drug
            count += 1

        logger.info(f"DGDA: allopathic medicine table yielded {count} drugs")

        # 2. Scrape Generic list for DCC numbers (supplementary)
        gen_count = 0
        async for drug in self._scrape_table(
            url=f"{_ALLOPATHIC_BASE}/?Generic_List_With_DCC_Number",
            source_label="dgda-generic",
            generic_only=True,
        ):
            yield drug
            gen_count += 1

        logger.info(f"DGDA: generic list yielded {gen_count} entries")

        # 3. OtherTMS (herbal/homeopathic/unani)
        other_count = 0
        async for drug in self._scrape_table(
            url=f"{_OTHERTMS_BASE}/?Medicine_Information",
            source_label="dgda-other",
        ):
            yield drug
            other_count += 1

        logger.info(f"DGDA: OtherTMS medicine table yielded {other_count} drugs")

    async def _scrape_table(
        self,
        url: str,
        source_label: str,
        generic_only: bool = False,
    ) -> AsyncIterator[Drug]:
        """Parse a DGDA DataTable page and yield Drug objects from each row."""
        try:
            page = await self.fetch_page(url)
        except Exception as e:
            logger.warning(f"DGDA: failed to fetch {url}: {e}")
            return

        # DataTables renders as <table id="example"> with <thead> and <tbody>
        table = page.css_first("table#example, table.dataTable, table")
        if not table:
            logger.warning(f"DGDA: no table found at {url}")
            return

        # Parse header row to map column names → indices
        headers: list[str] = []
        for th in table.css("thead th, thead td"):
            headers.append(_text(th).lower().strip())

        if not headers:
            # Try first <tr> as header
            first_row = table.css_first("tr")
            if first_row:
                for cell in first_row.css("th, td"):
                    headers.append(_text(cell).lower().strip())

        logger.debug(f"DGDA [{source_label}]: headers = {headers}")

        # Column index helpers
        def col(name: str, *aliases: str) -> int:
            for candidate in (name, *aliases):
                for i, h in enumerate(headers):
                    if candidate in h:
                        return i
            return -1

        idx_brand      = col("brand", "trade", "medicine name", "product name")
        idx_generic    = col("generic", "molecule", "inn")
        idx_company    = col("company", "manufacturer", "firm")
        idx_strength   = col("strength", "dose")
        idx_form       = col("form", "dosage form", "type")
        idx_price      = col("price", "mrp", "unit price")
        idx_reg        = col("reg", "dcc", "registration", "dar no")
        idx_category   = col("category", "group", "class")

        rows_yielded = 0
        for row in table.css("tbody tr"):
            cells = row.css("td")
            if not cells:
                continue

            def cell(idx: int) -> str:
                if 0 <= idx < len(cells):
                    return _text(cells[idx])
                return ""

            if generic_only:
                generic_name = cell(0) or cell(1)
                dcc_number   = cell(idx_reg) if idx_reg >= 0 else ""
                if not generic_name:
                    continue
                yield Drug(
                    source="dgda",
                    source_url=_CANONICAL_URL,
                    generic_name=generic_name,
                    registration_number=dcc_number,
                    categories=["Bangladesh", "DGDA", "Allopathic"],
                    extra={
                        "source_label": source_label,
                        "official_govt_data": True,
                        "dcc_number": dcc_number,
                    },
                )
                rows_yielded += 1
                continue

            # Full medicine row
            brand_name  = cell(idx_brand)  if idx_brand  >= 0 else cell(0)
            generic_name = cell(idx_generic) if idx_generic >= 0 else cell(1)
            company     = cell(idx_company) if idx_company >= 0 else ""
            strength    = cell(idx_strength) if idx_strength >= 0 else ""
            form        = cell(idx_form)   if idx_form   >= 0 else ""
            price_text  = cell(idx_price)  if idx_price  >= 0 else ""
            reg_no      = cell(idx_reg)    if idx_reg    >= 0 else ""
            category    = cell(idx_category) if idx_category >= 0 else ""

            if not brand_name and not generic_name:
                continue

            price = _parse_price(price_text)

            yield Drug(
                source="dgda",
                source_url=_CANONICAL_URL,
                brand_name=brand_name or None,
                generic_name=generic_name or None,
                strength=strength or None,
                dosage_form=form or None,
                registration_number=reg_no or None,
                manufacturer=Manufacturer(name=company, country="Bangladesh") if company else None,
                price=price,
                therapeutic_class=category or None,
                categories=["Bangladesh", "DGDA", source_label.split("-")[-1].title()],
                extra={
                    "source_label": source_label,
                    "official_govt_data": True,
                    "reg_number": reg_no,
                    "raw_row": [_text(c) for c in cells],
                },
            )
            rows_yielded += 1

        logger.info(f"DGDA [{source_label}]: parsed {rows_yielded} rows from {url}")


def _text(elem) -> str:
    if elem is None:
        return ""
    t = elem.text if hasattr(elem, "text") else ""
    return (t or "").strip()


def _parse_price(text: str) -> DrugPrice | None:
    if not text:
        return None
    nums = re.findall(r"[\d.]+", text)
    if nums:
        return DrugPrice(amount=float(nums[0]), currency="BDT", unit=text)
    return None
