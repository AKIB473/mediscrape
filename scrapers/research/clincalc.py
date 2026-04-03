"""ClinCalc scraper - clincalc.com/DrugStats - US prescription utilization data."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class ClinCalcScraper(BaseScrapingScraper):
    name = "clincalc"
    base_url = "https://clincalc.com"
    rate_limit = 1.5

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # ClinCalc has a top 300 drugs page
        try:
            page = await self.fetch_page(f"{self.base_url}/DrugStats/Top300Drugs.aspx")
        except Exception as e:
            logger.error(f"ClinCalc: failed to load main page: {e}")
            return

        jsonld = self.extract_jsonld(page)

        # Parse the main table
        table = page.css_first("table")
        if not table:
            logger.error("ClinCalc: no table found")
            return

        rows = table.css("tr")
        headers = [_text(th).lower() for th in rows[0].css("th")] if rows else []

        for row in rows[1:]:
            cells = row.css("td")
            if len(cells) < 3:
                continue

            data = {}
            for i, cell in enumerate(cells):
                key = headers[i] if i < len(headers) else f"col_{i}"
                data[key] = _text(cell)

            # Get link to detail page
            detail_link = row.css_first("a")
            detail_url = ""
            if detail_link:
                href = detail_link.attrib.get("href", "")
                detail_url = href if href.startswith("http") else f"{self.base_url}/DrugStats/{href}"

            drug_name = data.get("drug name", data.get("drug", _text(cells[0])))
            if not drug_name:
                continue

            # Try to scrape detail page for more info
            detail_data = {}
            if detail_url:
                try:
                    detail_data = await self._scrape_detail(detail_url)
                except Exception:
                    pass

            rank_text = data.get("rank", data.get("#", ""))
            prescriptions = data.get("total prescriptions", data.get("prescriptions", ""))

            yield Drug(
                source="clincalc",
                source_url=detail_url or f"{self.base_url}/DrugStats/Top300Drugs.aspx",
                brand_name=drug_name,
                generic_name=detail_data.get("generic_name", ""),
                drug_class=detail_data.get("drug_class", ""),
                categories=[detail_data["drug_class"]] if detail_data.get("drug_class") else [],
                extra={
                    "jsonld": jsonld,
                    "rank": _int(rank_text),
                    "total_prescriptions": prescriptions,
                    "total_patients": data.get("total patients", ""),
                    "change": data.get("change", data.get("% change", "")),
                    "clinical_use": detail_data.get("clinical_use", ""),
                    "prescription_trend": detail_data.get("trend", ""),
                    **{k: v for k, v in detail_data.items()},
                },
            )

    async def _scrape_detail(self, url: str) -> dict:
        page = await self.fetch_page(url)
        data = {}

        # Extract drug details
        fields = {}
        for row in page.css("tr, .detail-item"):
            label = _text(row.css_first("th, .label, dt"))
            value = _text(row.css_first("td, .value, dd"))
            if label and value:
                fields[label.lower().strip().rstrip(":")] = value

        data["generic_name"] = fields.get("generic name", "")
        data["drug_class"] = fields.get("drug class", fields.get("class", ""))
        data["clinical_use"] = fields.get("clinical use", fields.get("indication", ""))

        # Parse yearly data from tables/charts
        yearly_data = {}
        tables = page.css("table")
        for table in tables:
            for row in table.css("tr"):
                cells = row.css("td")
                if len(cells) >= 2:
                    year = _text(cells[0])
                    value = _text(cells[1])
                    if re.match(r"20\d{2}", year):
                        yearly_data[year] = value

        if yearly_data:
            data["yearly_prescriptions"] = yearly_data

        return data


def _text(elem) -> str:
    if elem is None:
        return ""
    return elem.text.strip() if hasattr(elem, "text") and elem.text else ""


def _int(text: str) -> int | None:
    nums = re.findall(r"\d+", text)
    if nums:
        return int(nums[0])
    return None
