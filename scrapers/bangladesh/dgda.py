"""DGDA scraper - dgda.gov.bd - Official govt drug registration database.

Verified structure (2026-05):
  Primary DB: http://180.211.137.202:9310/Allopathic/
  DataTables server-side AJAX endpoint:
    /Allopathic/Medicine_Information_Ajax.php?action=list
    Params: draw, start, length, search[value], search[regex]
    Returns JSON: {draw, recordsTotal, recordsFiltered, data: [[sl,company,trade,generic+strength,form,dar,price_html],...]}
    Total: ~41,082 drugs

  Other tabs (Generic_List, Trade/Generic/Company search) also have Ajax endpoints
  but Medicine_Information covers all fields we need.

  Price detail:
    /Allopathic/?Medicine_Price_Detail/{company}/{trade}/{generic}/{id}
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseAPIScraper

logger = logging.getLogger(__name__)

_AJAX_BASE   = "http://180.211.137.202:9310/Allopathic"
_CANONICAL_URL = "https://dgda.gov.bd"
_PAGE_SIZE   = 500   # DataTables page size per request


class DGDAScraper(BaseAPIScraper):
    """Scrape DGDA drug database via its DataTables server-side AJAX API."""

    name = "dgda"
    base_url = _AJAX_BASE
    rate_limit = 0.3   # Internal govt server; be polite but it's fast
    timeout    = 30.0
    headers = {
        "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "X-Requested-With": "XMLHttpRequest",
        "Referer":          f"{_AJAX_BASE}/?Medicine_Information",
    }

    async def scrape_all(self) -> AsyncIterator[Drug]:
        ajax_url = f"{_AJAX_BASE}/Medicine_Information_Ajax.php"
        start    = 0
        total    = None

        while True:
            try:
                resp = await self.api_get(
                    ajax_url,
                    params={
                        "action":         "list",
                        "draw":           (start // _PAGE_SIZE) + 1,
                        "start":          start,
                        "length":         _PAGE_SIZE,
                        "search[value]":  "",
                        "search[regex]":  "false",
                    },
                )
            except Exception as e:
                logger.error(f"DGDA: AJAX request failed at start={start}: {e}")
                break

            if total is None:
                total = resp.get("recordsTotal", 0)
                logger.info(f"DGDA: {total} total drugs in database")

            rows = resp.get("data", [])
            if not rows:
                break

            for row in rows:
                drug = self._parse_row(row)
                if drug:
                    yield drug

            start += _PAGE_SIZE
            if start >= total:
                break

        logger.info(f"DGDA: finished scraping (requested {start} of {total})")

    def _parse_row(self, row: list) -> Drug | None:
        """
        Row format (confirmed from live API 2026-05):
          [0] SL (int)
          [1] Company name (str)
          [2] Trade Name / Brand (str)
          [3] Generic Name With Strength (str)  e.g. "Lidocaine Hydrochloride 10 mg/ml"
          [4] Dosage Form (str)
          [5] DAR No / Registration No (str)
          [6] Price link HTML (str)  e.g. <a href="?Medicine_Price_Detail/...">Click Here</a>
        """
        if not row or len(row) < 3:
            return None

        company       = str(row[1]).strip() if len(row) > 1 else ""
        trade_name    = str(row[2]).strip() if len(row) > 2 else ""
        generic_str   = str(row[3]).strip() if len(row) > 3 else ""
        dosage_form   = str(row[4]).strip() if len(row) > 4 else ""
        dar_no        = str(row[5]).strip() if len(row) > 5 else ""
        price_html    = str(row[6]).strip() if len(row) > 6 else ""

        if not trade_name and not generic_str:
            return None

        # Split generic name and strength from "GenericName StrengthValue unit"
        generic_name, strength = _split_generic_strength(generic_str)

        # Extract price detail URL from HTML link
        price_url_match = re.search(r'href="([^"]+)"', price_html)
        price_detail_path = price_url_match.group(1) if price_url_match else ""

        return Drug(
            source="dgda",
            source_url=_CANONICAL_URL,
            brand_name=trade_name or None,
            generic_name=generic_name or None,
            strength=strength or None,
            dosage_form=dosage_form or None,
            registration_number=dar_no or None,
            manufacturer=Manufacturer(name=company, country="Bangladesh") if company else None,
            categories=["Bangladesh", "DGDA", "Registered"],
            extra={
                "official_govt_data": True,
                "dar_number": dar_no,
                "price_detail_path": price_detail_path,
                "generic_with_strength_raw": generic_str,
            },
        )


def _split_generic_strength(text: str) -> tuple[str, str]:
    """
    Split 'Amoxicillin Trihydrate 500 mg' → ('Amoxicillin Trihydrate', '500 mg')
    Also handles: '500mg/5ml', '10 mg/ml', '0.5% w/v', etc.
    """
    if not text:
        return "", ""

    # Match strength pattern at end: digits + optional decimal + unit
    m = re.search(
        r"\s+(\d[\d,./]*\s*(?:mg|mcg|g|ml|iu|%|mmol|meq|unit|million|mega|micro|nano)[\w/]*(?:\s*/\s*\d[\d.]*\s*\w+)*)\s*$",
        text,
        re.IGNORECASE,
    )
    if m:
        strength = m.group(1).strip()
        generic  = text[:m.start()].strip()
        return generic, strength

    return text, ""
