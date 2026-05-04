"""MedEx scraper - medex.com.bd - 25k+ brands, generics, prices, side effects, interactions.

Structure (from research):
- Brands listing: /brands?page={n} (839 pages), /brands?alpha={letter}&page={n}
- Brand detail: /brands/{id}/{slug}
- Generics listing: /generics?page={n} (83 pages)
- Generic detail: /generics/{id}/{slug}
- AJAX search: /ajax/search?q={query}
- Server-rendered HTML, no JS needed
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class MedExScraper(BaseScrapingScraper):
    name = "medex"
    base_url = "https://medex.com.bd"
    rate_limit = 1.0

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Scrape brands incrementally (page by page, yield as we go)
        page_num = 1
        while True:
            brand_urls = []
            try:
                page = await self.fetch_page(f"{self.base_url}/brands?page={page_num}")
                for link in page.css('a[href*="/brands/"]'):
                    href = link.attrib.get("href", "")
                    if href and re.search(r"/brands/\d+", href):
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        brand_urls.append(full)
                if not brand_urls:
                    break
            except Exception:
                break

            for url in brand_urls:
                try:
                    drug = await self._scrape_brand_page(url)
                    if drug:
                        yield drug
                except Exception as e:
                    logger.warning(f"MedEx: error scraping {url}: {e}")
            page_num += 1

        # Also scrape generic pages incrementally
        page_num = 1
        while True:
            generic_urls = []
            try:
                page = await self.fetch_page(f"{self.base_url}/generics?page={page_num}")
                for link in page.css('a[href*="/generics/"]'):
                    href = link.attrib.get("href", "")
                    if href and re.search(r"/generics/\d+", href):
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        generic_urls.append(full)
                if not generic_urls:
                    break
            except Exception:
                break

            for url in generic_urls:
                try:
                    async for drug in self._scrape_generic_page(url):
                        yield drug
                except Exception as e:
                    logger.warning(f"MedEx: error scraping generic {url}: {e}")
            page_num += 1

    async def _scrape_brand_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        title = _text(page.css_first("h1"))
        if not title:
            return None

        # MedEx specific: generic name is in a dedicated element near the header
        # e.g. <div class='generic-name'>Vitamin B1, B6 & B12</div>
        # or appears in the header block as text after the brand name
        generic_name = ""
        # Try dedicated generic name element
        for sel in [".generic-name", ".generic_name", "[class*='generic-name']",
                    ".product-generic", ".medicine-generic"]:
            elem = page.css_first(sel)
            if elem:
                generic_name = _text(elem)
                break
        # Fallback: look for a standalone link/span that points to a /generics/ URL
        if not generic_name:
            for link in page.css('a[href*="/generics/"]'):
                t = _text(link)
                if t and len(t) > 2:
                    generic_name = t
                    break
        # Fallback: check JSON-LD for generic info
        if not generic_name and jsonld:
            for ld in jsonld:
                if isinstance(ld, dict):
                    g = ld.get("activeIngredient") or ld.get("nonProprietaryName")
                    if g:
                        generic_name = g if isinstance(g, str) else ""
                        break

        # Extract key-value fields from the detail table
        fields = {}
        for row in page.css("tr"):
            cells = row.css("td")
            if len(cells) >= 2:
                key = _text(cells[0]).lower().strip().rstrip(":")
                val = _text(cells[1])
                if key and val:
                    fields[key] = val
            # Also try th/td pairs
            th = row.css_first("th")
            td = row.css_first("td")
            if th and td:
                key = _text(th).lower().strip().rstrip(":")
                val = _text(td)
                if key and val:
                    fields[key] = val

        # Extract sections (indications, side effects, etc.) using MedEx structure
        # MedEx uses h3 headings with content in following div/p siblings
        sections = {}
        # Try the generic-data-container which holds all clinical sections
        data_container = page.css_first(".generic-data-container, .drug-details, .medicine-details")
        container_to_search = data_container if data_container else page
        current_key = ""
        for elem in container_to_search.css("h2, h3, h4, p, div, ul li"):
            tag = getattr(elem, 'tag', '') or ''
            text = _text(elem)
            if tag in ("h2", "h3", "h4"):
                current_key = text.lower().strip()
            elif current_key and text and len(text) > 5:
                if current_key not in sections:
                    sections[current_key] = text
                else:
                    sections[current_key] += "\n" + text

        # Fallback section extraction for older structure
        if not sections:
            for heading in page.css("h2, h3, h4, .section-title"):
                key = _text(heading).lower().strip()
                content_parts = []
                parent = heading.parent
                if parent:
                    for child in parent.css("p, ul li, ol li, div.content"):
                        t = _text(child)
                        if t and len(t) > 3:
                            content_parts.append(t)
                if content_parts:
                    sections[key] = "\n".join(content_parts)

        if not generic_name:
            generic_name = fields.get("generic", fields.get("generic name", ""))
        manufacturer_name = fields.get("manufacturer", fields.get("company", fields.get("marketed by", "")))
        # MedEx shows manufacturer as plain text in header block
        if not manufacturer_name:
            mfr_elem = page.css_first(".manufacturer, .company-name, [class*='pharma']")
            if mfr_elem:
                manufacturer_name = _text(mfr_elem)
        price_text = fields.get("unit price", fields.get("price", fields.get("mrp", "")))
        # MedEx shows price in .package-container
        if not price_text:
            pkg = page.css_first(".package-container, .packages-wrapper")
            if pkg:
                price_text = _text(pkg)
        strength = fields.get("strength", fields.get("dose", ""))
        dosage_form = fields.get("dosage form", fields.get("type", ""))
        therapeutic_class = fields.get("therapeutic class", fields.get("class", ""))
        # MedEx therapeutic class is in a dedicated section
        if not therapeutic_class:
            tc_text = sections.get("therapeutic class", "")
            if tc_text:
                therapeutic_class = tc_text.split("\n")[0].strip()
        pack_size = fields.get("pack size", "")

        return Drug(
            source="medex",
            source_url=url,
            brand_name=title,
            generic_name=generic_name,
            strength=strength,
            dosage_form=dosage_form,
            therapeutic_class=therapeutic_class,
            manufacturer=Manufacturer(name=manufacturer_name, country="Bangladesh") if manufacturer_name else None,
            price=_parse_price(price_text),
            indications=_split(sections.get("indications", sections.get("indication", ""))),
            contraindications=_split(sections.get("contraindications", sections.get("contraindication", ""))),
            side_effects=_split(sections.get("side effects", sections.get("adverse effects", ""))),
            adverse_reactions=_split(sections.get("adverse reactions", "")),
            interactions=_split(sections.get("drug interaction", sections.get("interactions", ""))),
            warnings=_split(sections.get("warnings", sections.get("warning", ""))),
            precautions=_split(sections.get("precautions", sections.get("precaution", ""))),
            dosage=sections.get("dosage", sections.get("dosage & administration", sections.get("dose", ""))),
            adult_dose=sections.get("adult dose", ""),
            pediatric_dose=sections.get("pediatric dose", sections.get("children dose", "")),
            mechanism_of_action=sections.get("mode of action", sections.get("mechanism of action", sections.get("pharmacology", ""))),
            pharmacokinetics={"description": sections["pharmacokinetics"]} if sections.get("pharmacokinetics") else None,
            pregnancy_category=sections.get("pregnancy category", sections.get("pregnancy", fields.get("pregnancy category", ""))),
            lactation=sections.get("lactation", sections.get("breastfeeding", "")),
            overdose=sections.get("overdose", sections.get("overdosage", "")),
            storage=sections.get("storage", sections.get("storage conditions", fields.get("storage", ""))),
            description=sections.get("description", ""),
            extra={
                "jsonld": jsonld,
                "pack_size": pack_size,
                "administration": sections.get("administration", ""),
                "reconstitution": sections.get("reconstitution", ""),
                "duration": sections.get("duration of treatment", ""),
                "all_fields": fields,
                "all_sections": {k: v for k, v in sections.items()},
            },
        )

    async def _scrape_generic_page(self, url: str) -> AsyncIterator[Drug]:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        generic_name = _text(page.css_first("h1"))
        if not generic_name:
            return

        # Extract clinical sections
        sections = {}
        for heading in page.css("h2, h3, h4, .section-title"):
            key = _text(heading).lower().strip()
            content_parts = []
            parent = heading.parent
            if parent:
                for child in parent.css("p, ul li, ol li, div"):
                    t = _text(child)
                    if t and len(t) > 3:
                        content_parts.append(t)
            if content_parts:
                sections[key] = "\n".join(content_parts)

        # Look for brand table on generic page
        brand_rows = page.css("table tr")
        for row in brand_rows:
            cells = row.css("td")
            if len(cells) >= 3:
                brand = _text(cells[0])
                if not brand or brand.lower() in ("brand name", "brand", "name", ""):
                    continue

                strength = _text(cells[1]) if len(cells) > 1 else ""
                form = _text(cells[2]) if len(cells) > 2 else ""
                company = _text(cells[3]) if len(cells) > 3 else ""
                price_text = _text(cells[4]) if len(cells) > 4 else ""
                pack = _text(cells[5]) if len(cells) > 5 else ""

                yield Drug(
                    source="medex",
                    source_url=url,
                    brand_name=brand,
                    generic_name=generic_name,
                    strength=strength,
                    dosage_form=form,
                    manufacturer=Manufacturer(name=company, country="Bangladesh") if company else None,
                    price=_parse_price(price_text),
                    indications=_split(sections.get("indications", "")),
                    contraindications=_split(sections.get("contraindications", "")),
                    side_effects=_split(sections.get("side effects", "")),
                    interactions=_split(sections.get("drug interaction", "")),
                    dosage=sections.get("dosage", ""),
                    mechanism_of_action=sections.get("mode of action", ""),
                    pregnancy_category=sections.get("pregnancy", ""),
                    storage=sections.get("storage", ""),
                    extra={
                        "jsonld": jsonld,
                        "pack_size": pack,
                        "sections": sections,
                    },
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
    items = re.split(r"[•\n;]", text)
    return [i.strip() for i in items if i.strip()]
