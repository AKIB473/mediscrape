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

        # scrapling Fetcher may return empty .text on some pages;
        # use page.get_text() or re-fetch via httpx as fallback
        page_html = ""
        if hasattr(page, "text") and page.text:
            page_html = page.text
        elif hasattr(page, "get_text"):
            page_html = page.get_text()

        if not page_html or "tableTopDrugs" not in page_html:
            # Re-fetch via httpx which reliably returns full HTML
            try:
                import httpx as _httpx
                async with _httpx.AsyncClient(
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                    follow_redirects=True, timeout=20,
                ) as _c:
                    _r = await _c.get(f"{self.base_url}/DrugStats/Top300Drugs.aspx")
                    page_html = _r.text
            except Exception as e:
                logger.error(f"ClinCalc: httpx fallback failed: {e}")
                return

        # Use BeautifulSoup for reliable table parsing
        from bs4 import BeautifulSoup as _BS
        soup = _BS(page_html, "html.parser")
        # ClinCalc uses id='tableTopDrugs'
        table_el = (
            soup.find("table", id="tableTopDrugs")
            or soup.find("table", id=re.compile(r"drug|top|stat", re.I))
            or soup.find("table")
        )
        if not table_el:
            logger.error("ClinCalc: no table found on page")
            return

        # Build header map
        header_row = table_el.find("tr")
        headers = [th.get_text(strip=True).lower() for th in (header_row.find_all(["th", "td"]) if header_row else [])]
        logger.info(f"ClinCalc: headers = {headers}")

        data_rows = table_el.find_all("tr")[1:] if header_row else table_el.find_all("tr")

        for row in data_rows:
            soup_cells = row.find_all("td")
            if len(soup_cells) < 3:
                continue

            data = {}
            for i, cell in enumerate(soup_cells):
                key = headers[i] if i < len(headers) else f"col_{i}"
                data[key] = cell.get_text(strip=True)

            # Get link to detail page
            link_tag = row.find("a")
            detail_url = ""
            if link_tag and link_tag.get("href"):
                href = link_tag["href"]
                detail_url = href if href.startswith("http") else f"{self.base_url}/DrugStats/{href}"

            drug_name = data.get("drug name", data.get("drug", soup_cells[0].get_text(strip=True) if soup_cells else ""))
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
        import re as _re
        page = await self.fetch_page(url)
        page_html = page.text if hasattr(page, 'text') else ''
        data = {}

        # Parse via regex on raw HTML (more reliable than CSS on _HTMLPage)
        if page_html:
            # Key-value table rows: <th>Label</th><td>Value</td>
            kv = _re.findall(
                r'<th[^>]*>([^<]{2,60})</th>\s*<td[^>]*>([^<]{2,200})</td>',
                page_html, _re.IGNORECASE
            )
            fields = {k.strip().lower().rstrip(':'): v.strip() for k,v in kv}
            # Also try definition lists
            dts = _re.findall(r'<dt[^>]*>([^<]{2,60})</dt>\s*<dd[^>]*>([^<]{2,200})</dd>', page_html)
            for k,v in dts:
                fields[k.strip().lower()] = v.strip()

            data['generic_name'] = (
                fields.get('generic name') or
                fields.get('generic') or
                fields.get('nonproprietary name') or ''
            )
            data['drug_class'] = fields.get('drug class', fields.get('class', ''))
            data['clinical_use'] = fields.get('clinical use', fields.get('indication', ''))
            data['atc_code'] = fields.get('atc code', fields.get('atc', ''))
        else:
            # CSS fallback
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
