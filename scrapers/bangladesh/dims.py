"""DIMS scraper - dimsbd.com - 28k+ brands, 2228 generics, FDA pregnancy categories.

Note: Research found dimsbd.com drug data is app-only; website is mostly marketing.
This scraper attempts to extract whatever is available from the web pages.
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class DIMSScraper(BaseScrapingScraper):
    name = "dims"
    base_url = "https://www.dimsbd.com"
    rate_limit = 1.5

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # DIMS has generic drug pages accessible via /generic/ path
        generics = await self._get_all_generics()
        logger.info(f"DIMS: found {len(generics)} generic URLs")

        for url in generics:
            try:
                async for drug in self._scrape_generic_page(url):
                    yield drug
            except Exception as e:
                logger.warning(f"DIMS: error scraping {url}: {e}")

    async def _get_all_generics(self) -> list[str]:
        """
        DIMS generics/brands index pages list drug names as plain text (not links) —
        actual drug content is app-only (requires DIMS Premium mobile app).
        We convert the visible generic names to slug-based URLs and try fetching
        individual pages for whatever the web server exposes.
        """
        import re as _re

        generic_names: list[str] = []
        letters = ["numeric"] + list("abcdefghijklmnopqrstuvwxyz")

        for letter in letters:
            try:
                page = await self.fetch_page(f"{self.base_url}/generics/{letter}")
                # Links to individual generic pages may or may not exist;
                # try both href-based and text-based extraction
                for link in page.css('a[href*="/generics/"]'):
                    href = link.attrib.get("href", "")
                    suffix = href.rstrip("/").split("/")[-1]
                    if href and suffix not in letters and len(suffix) > 2:
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        generic_names.append(full)

                # Fallback: extract plain-text names and build slugged URLs
                for elem in page.css("li, .generic-item, p"):
                    name = _text(elem).strip()
                    if name and 3 < len(name) < 120 and _re.match(r"^[A-Za-z]", name):
                        slug = name.lower().strip()
                        slug = _re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
                        url = f"{self.base_url}/generics/{slug}"
                        if url not in generic_names:
                            generic_names.append(url)
            except Exception:
                pass

        return generic_names

    async def _scrape_generic_page(self, url: str) -> AsyncIterator[Drug]:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        generic_name = _text(page.css_first("h1, .generic-name"))

        # Extract all text sections
        sections = {}
        current_heading = ""
        for elem in page.css("h2, h3, h4, p, div.content, .section"):
            tag = elem.tag if hasattr(elem, "tag") else ""
            text = _text(elem)
            if tag in ("h2", "h3", "h4"):
                current_heading = text.lower()
            elif current_heading and text:
                sections.setdefault(current_heading, []).append(text)

        section_text = {k: "\n".join(v) for k, v in sections.items()}

        # Parse pregnancy category - DIMS speciality
        pregnancy_cat = ""
        for key in section_text:
            if "pregnancy" in key:
                pregnancy_cat = section_text[key]
                break
        if not pregnancy_cat:
            preg_elem = page.css_first(".pregnancy-category, [class*=pregnancy]")
            if preg_elem:
                pregnancy_cat = _text(preg_elem)

        # Look for brand listings
        brand_rows = page.css("table tr, .brand-item, .brand-card, [class*=brand-list] a")

        if brand_rows:
            for row in brand_rows:
                cells = row.css("td")
                if len(cells) >= 2:
                    brand = _text(cells[0])
                    strength = _text(cells[1]) if len(cells) > 1 else None
                    form = _text(cells[2]) if len(cells) > 2 else None
                    company = _text(cells[3]) if len(cells) > 3 else None
                    price_text = _text(cells[4]) if len(cells) > 4 else None
                    pack = _text(cells[5]) if len(cells) > 5 else None

                    if not brand or brand.lower() in ("brand name", "brand", "name"):
                        continue

                    price = _parse_price(price_text)

                    yield Drug(
                        source="dims",
                        source_url=url,
                        brand_name=brand,
                        generic_name=generic_name,
                        strength=strength,
                        dosage_form=form,
                        manufacturer=Manufacturer(name=company) if company else None,
                        price=price,
                        pregnancy_category=pregnancy_cat,
                        indications=_split(section_text.get("indications", section_text.get("indication", ""))),
                        contraindications=_split(section_text.get("contraindications", "")),
                        side_effects=_split(section_text.get("side effects", section_text.get("adverse effects", ""))),
                        interactions=_split(section_text.get("interactions", section_text.get("drug interactions", ""))),
                        dosage=section_text.get("dosage", section_text.get("dose", "")),
                        mechanism_of_action=section_text.get("mode of action", section_text.get("pharmacology", "")),
                        warnings=_split(section_text.get("warnings", "")),
                        precautions=_split(section_text.get("precautions", "")),
                        storage=section_text.get("storage", ""),
                        extra={
                            "jsonld": jsonld,
                            "pack_size": pack,
                            "fda_pregnancy_category": pregnancy_cat,
                            "sections": section_text,
                        },
                    )
                else:
                    # Try parsing as a link/card
                    brand = _text(row)
                    if brand and len(brand) < 200:
                        yield Drug(
                            source="dims",
                            source_url=url,
                            brand_name=brand,
                            generic_name=generic_name,
                            pregnancy_category=pregnancy_cat,
                            extra={"jsonld": jsonld, "sections": section_text},
                        )
        else:
            # Single generic info page
            yield Drug(
                source="dims",
                source_url=url,
                generic_name=generic_name,
                pregnancy_category=pregnancy_cat,
                indications=_split(section_text.get("indications", "")),
                contraindications=_split(section_text.get("contraindications", "")),
                side_effects=_split(section_text.get("side effects", "")),
                interactions=_split(section_text.get("interactions", "")),
                dosage=section_text.get("dosage", ""),
                mechanism_of_action=section_text.get("mode of action", ""),
                extra={"jsonld": jsonld, "sections": section_text},
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


def _split(text: str) -> list[str]:
    if not text:
        return []
    return [i.strip() for i in re.split(r"[•\n;]", text) if i.strip()]
