"""MedEx scraper - medex.com.bd - 25k+ brands, generics, prices, side effects, interactions.

Structure (verified 2026-05):
- Brands listing: /brands?page={n} (839 pages)
- Brand detail: /brands/{id}/{slug}  — server-rendered HTML, no JS needed
- Generics listing: /generics?page={n} (83 pages)
- Generic detail: /generics/{id}/{slug}

Page structure:
  <h1>  — brand name (with strength/form embedded, e.g. "Napa 500 mg Tablet")
  .generic-name or a[href*=/generics/]  — generic drug name
  .package-container  — prices per pack
  sections via h3 headings: Indications, Pharmacology, Dosage, Interaction,
    Contraindications, Side Effects, Pregnancy & Lactation, Precautions & Warnings,
    Overdose Effects, Therapeutic Class, Storage Conditions, Chemical Structure

Fix (2026-05):
  - Parse dosage_form and strength directly from brand name string
  - Clean up sections (deduplicate repeated content)
  - Clean price text properly
  - Extract molecular_formula from Chemical Structure section
"""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)

# Known dosage form keywords — order matters (longer first)
_FORMS = [
    "powder for suspension", "powder for injection", "powder for oral suspension",
    "oral solution", "oral suspension", "oral drops",
    "eye drop", "ear drop", "nasal drop", "nasal spray",
    "eye ointment", "ear ointment", "rectal suppository",
    "extended release tablet", "sustained release tablet", "modified release tablet",
    "effervescent tablet", "chewable tablet", "dispersible tablet", "sublingual tablet",
    "film coated tablet", "film-coated tablet",
    "sustained release capsule", "extended release capsule", "modified release capsule",
    "hard capsule", "soft capsule",
    "tablet", "capsule", "syrup", "suspension", "solution", "injection",
    "cream", "ointment", "gel", "lotion", "suppository", "patch",
    "inhaler", "spray", "drops", "powder", "granules", "sachet",
    "infusion", "emulsion", "foam", "shampoo",
]


def _extract_form_strength(name: str) -> tuple[str, str]:
    """
    Parse dosage form and strength from a brand name string.
    e.g. "Napa 500 mg Tablet" → ("Tablet", "500 mg")
         "Seclo 20 Capsule" → ("Capsule", "20 mg")
         "Amoxil 125 mg/5 ml Suspension" → ("Suspension", "125 mg/5 ml")
    """
    name_lower = name.lower()
    form = ""
    for f in _FORMS:
        if f in name_lower:
            form = f.title()
            break

    # Strength patterns: 500mg, 500 mg, 125mg/5ml, 125 mg/5 ml, 0.5%, 0.5 mg/kg
    strength_match = re.search(
        r"(\d+(?:\.\d+)?\s*(?:mg|mcg|µg|g|iu|iu|unit|%)(?:/\s*\d+(?:\.\d+)?\s*(?:ml|l|g|mg))?)",
        name,
        re.IGNORECASE,
    )
    strength = strength_match.group(0).strip() if strength_match else ""

    return form, strength


def _clean_section(text: str, section_name: str) -> str:
    """
    Clean up a section's text:
    - Remove the section heading if it appears at the end
    - Remove navigation noise (Bengali disclaimer, heading repeats)
    - Strip trailing whitespace
    """
    if not text:
        return ""

    # Remove the repeated section heading that medex appends at the end
    # e.g. "...text...\nSide Effects\n        \n                ...\nSide Effects"
    # The pattern is: heading appears twice — once after \n\n and once more at the end
    lines = text.splitlines()

    # Remove lines that are just the section heading repeated or medex boilerplate
    boilerplate = {
        "* রেজিস্টার্ড চিকিৎসকের পরামর্শ মোতাবেক ঔষধ সেবন করুন'",
        "* রেজিস্টার্ড চিকিৎসকের পরামর্শ মোতাবেক ঔষধ সেবন করুন",
    }

    heading_variants = {section_name.lower(), section_name.title().lower()}
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in boilerplate:
            continue
        if stripped.lower() in heading_variants:
            continue
        # Remove medex internal template fragments
        if re.match(r"^\s{8,}", line) and len(stripped) < 5:
            continue
        cleaned.append(stripped)

    # Deduplicate consecutive identical lines
    deduped = []
    for line in cleaned:
        if not deduped or line != deduped[-1]:
            deduped.append(line)

    result = "\n".join(deduped).strip()

    # If the entire content is just the section name, return empty
    if result.lower().strip() in heading_variants:
        return ""

    return result


def _parse_price_clean(text: str) -> DrugPrice | None:
    """
    Parse price from messy medex price text.
    e.g. "Unit Price:\n ৳ 35.00\n (12's pack: ৳ 420.00)"
    → DrugPrice(amount=35.0, currency="BDT", unit="per unit")
    """
    if not text:
        return None
    # Find all numbers in the text
    # Medex uses ৳ symbol for BDT
    unit_match = re.search(r"(?:unit\s*price[^৳\d]*|৳\s*)(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if unit_match:
        return DrugPrice(
            amount=float(unit_match.group(1)),
            currency="BDT",
            unit="per unit",
        )
    nums = re.findall(r"(\d+(?:\.\d+)?)", text)
    if nums:
        return DrugPrice(amount=float(nums[0]), currency="BDT")
    return None


def _split_clean(text: str) -> list[str]:
    """Split text into list items, deduplicate, clean."""
    if not text:
        return []
    # Split on bullets, newlines, semicolons
    items = re.split(r"[•\n;]", text)
    seen = set()
    result = []
    for item in items:
        item = item.strip()
        if item and len(item) > 5 and item not in seen:
            seen.add(item)
            result.append(item)
    return result


class MedExScraper(BaseScrapingScraper):
    name = "medex"
    base_url = "https://medex.com.bd"
    rate_limit = 0.8

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Scrape brands page by page
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
                    logger.warning(f"MedEx: brand error {url}: {e}")
            page_num += 1

        # Also scrape generics pages
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
                    logger.warning(f"MedEx: generic error {url}: {e}")
            page_num += 1

    async def _scrape_brand_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)

        # Brand name from h1
        h1 = page.css_first("h1")
        title = _text(h1)
        if not title:
            return None

        # Parse dosage form and strength from the brand name
        dosage_form, strength = _extract_form_strength(title)

        # Generic name: from dedicated element or link to /generics/
        # Extract from raw HTML directly (more reliable than CSS selector on _HTMLPage)
        generic_name = ""
        page_html = page.text if hasattr(page, "text") else ""
        if page_html:
            # medex pattern: <a href="/generics/123/generic-name">Generic Name</a>
            gn_match = re.search(
                r'<a[^>]+href=["\'][^"\']*/generics/\d+/[^"\'>]+["\'][^>]*>([^<]{3,80})</a>',
                page_html,
            )
            if gn_match:
                generic_name = gn_match.group(1).strip()
        if not generic_name:
            for link in page.css('a[href*="/generics/"]'):
                t = _text(link)
                if t and len(t) > 2 and len(t) < 100 and "\n" not in t:
                    generic_name = t
                    break

        # Manufacturer: look for company/manufacturer fields or known patterns
        manufacturer_name = ""
        for sel in [".manufacturer", ".company-name", "[class*='manufacturer']",
                    "[class*='company']", ".mfr"]:
            elem = page.css_first(sel)
            if elem:
                t = _text(elem)
                if t and len(t) > 2:
                    manufacturer_name = t
                    break
        # Also check table rows for "Manufacturer" key
        if not manufacturer_name:
            for row in page.css("tr"):
                th = row.css_first("th")
                td = row.css_first("td")
                if th and td:
                    key = _text(th).lower().strip().rstrip(":")
                    if "manufacturer" in key or "company" in key or "marketed" in key:
                        manufacturer_name = _text(td)
                        break

        # Price from .package-container or price elements
        price_text = ""
        for sel in [".package-container", ".packages-wrapper", ".price", "[class*=price]",
                    ".pack-price", ".unit-price"]:
            elem = page.css_first(sel)
            if elem:
                price_text = _text(elem)
                if price_text:
                    break

        # Extract sections using medex's section structure
        # Medex uses h3 headings followed by content in sibling/child elements
        sections: dict[str, str] = {}
        section_order = [
            "indications", "pharmacology", "dosage & administration",
            "interaction", "contraindications", "side effects",
            "pregnancy & lactation", "precautions & warnings", "overdose effects",
            "therapeutic class", "storage conditions", "chemical structure",
        ]

        # Parse the page HTML for section content
        page_html = page.text if hasattr(page, "text") else ""
        if page_html:
            sections = _parse_medex_sections(page_html)

        # Map section names to drug fields
        therapeutic_class = _clean_section(sections.get("therapeutic class", ""), "therapeutic class")
        if not therapeutic_class:
            therapeutic_class = _clean_section(sections.get("pharmacological class", ""), "pharmacological class")

        # Molecular formula from chemical structure section
        mol_formula = ""
        chem_section = sections.get("chemical structure", "")
        if chem_section:
            # Match full molecular formula e.g. C16H15N5O7S2
            mf_match = re.search(
                r"molecular formula\s*:?\s*([A-Z][A-Za-z0-9\s]+)",
                chem_section,
                re.IGNORECASE,
            )
            if mf_match:
                # Remove whitespace from formula (e.g. "C 16 H 15" → "C16H15")
                mol_formula = re.sub(r"\s+", "", mf_match.group(1)).strip()
                # Validate it looks like a real formula
                if not re.match(r"^[A-Z][A-Za-z0-9]+$", mol_formula):
                    mol_formula = ""

        # Pregnancy category — extract letter (A, B, C, D, X)
        preg_text = _clean_section(sections.get("pregnancy & lactation", ""), "pregnancy & lactation")
        preg_category = ""
        if preg_text:
            cat_match = re.search(r"\bCategory\s+([ABCDX])\b", preg_text, re.IGNORECASE)
            if cat_match:
                preg_category = cat_match.group(1)
            else:
                preg_category = preg_text[:200]  # keep full text if no category letter

        return Drug(
            source="medex",
            source_url=url,
            brand_name=title,
            generic_name=generic_name or None,
            dosage_form=dosage_form or None,
            strength=strength or None,
            therapeutic_class=therapeutic_class or None,
            manufacturer=Manufacturer(name=manufacturer_name, country="Bangladesh") if manufacturer_name else None,
            price=_parse_price_clean(price_text),
            indications=_split_clean(_clean_section(sections.get("indications", ""), "indications")),
            contraindications=_split_clean(_clean_section(sections.get("contraindications", ""), "contraindications")),
            side_effects=_split_clean(_clean_section(sections.get("side effects", ""), "side effects")),
            adverse_reactions=_split_clean(_clean_section(sections.get("adverse reactions", ""), "adverse reactions")),
            interactions=_split_clean(_clean_section(sections.get("interaction", ""), "interaction")),
            warnings=_split_clean(_clean_section(sections.get("precautions & warnings", ""), "precautions & warnings")),
            precautions=_split_clean(_clean_section(sections.get("precautions & warnings", ""), "precautions & warnings")),
            dosage=_clean_section(sections.get("dosage & administration", ""), "dosage & administration") or None,
            mechanism_of_action=_clean_section(sections.get("pharmacology", ""), "pharmacology") or None,
            pregnancy_category=preg_category or None,
            lactation=_clean_section(sections.get("pregnancy & lactation", ""), "pregnancy & lactation") or None,
            overdose=_clean_section(sections.get("overdose effects", ""), "overdose effects") or None,
            storage=_clean_section(sections.get("storage conditions", ""), "storage conditions") or None,
            molecular_formula=mol_formula or None,
            extra={
                "pack_size": _extract_pack_size(price_text),
                "all_sections": {k: v[:500] for k, v in sections.items()},
            },
        )

    async def _scrape_generic_page(self, url: str) -> AsyncIterator[Drug]:
        page = await self.fetch_page(url)

        generic_name = _text(page.css_first("h1"))
        if not generic_name:
            return

        # Parse sections
        page_html = page.text if hasattr(page, "text") else ""
        sections = _parse_medex_sections(page_html) if page_html else {}

        # Look for brand table
        brand_rows = page.css("table tr")
        yielded = 0
        for row in brand_rows:
            cells = row.css("td")
            if len(cells) < 2:
                continue
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
                strength=strength or None,
                dosage_form=form or None,
                manufacturer=Manufacturer(name=company, country="Bangladesh") if company else None,
                price=_parse_price_clean(price_text),
                indications=_split_clean(_clean_section(sections.get("indications", ""), "indications")),
                contraindications=_split_clean(_clean_section(sections.get("contraindications", ""), "contraindications")),
                side_effects=_split_clean(_clean_section(sections.get("side effects", ""), "side effects")),
                interactions=_split_clean(_clean_section(sections.get("interaction", ""), "interaction")),
                dosage=_clean_section(sections.get("dosage & administration", ""), "dosage & administration") or None,
                mechanism_of_action=_clean_section(sections.get("pharmacology", ""), "pharmacology") or None,
                pregnancy_category=_extract_preg_category(sections.get("pregnancy & lactation", "")),
                storage=_clean_section(sections.get("storage conditions", ""), "storage conditions") or None,
                extra={"pack_size": pack},
            )
            yielded += 1

        if yielded == 0:
            # Yield generic-only record
            yield Drug(
                source="medex",
                source_url=url,
                generic_name=generic_name,
                indications=_split_clean(_clean_section(sections.get("indications", ""), "indications")),
                contraindications=_split_clean(_clean_section(sections.get("contraindications", ""), "contraindications")),
                side_effects=_split_clean(_clean_section(sections.get("side effects", ""), "side effects")),
                interactions=_split_clean(_clean_section(sections.get("interaction", ""), "interaction")),
                dosage=_clean_section(sections.get("dosage & administration", ""), "dosage & administration") or None,
                mechanism_of_action=_clean_section(sections.get("pharmacology", ""), "pharmacology") or None,
                extra={"sections": {k: v[:500] for k, v in sections.items()}},
            )


# ------------------------------------------------------------------ #
# HTML section parser                                                   #
# ------------------------------------------------------------------ #

def _parse_medex_sections(html: str) -> dict[str, str]:
    """
    Parse medex page HTML into a dict of {section_name: clean_text}.
    Medex uses this pattern:
        <h3>Section Name</h3>
        <div class="...">
            <p>Content here</p>
        </div>
    Or sometimes:
        <div class="section-title">Section Name</div>
        <div class="section-content">Content</div>
    """
    sections: dict[str, str] = {}

    # Find all h3 headings and capture text until next h3
    heading_pattern = re.compile(
        r"<h[23][^>]*>(.*?)</h[23]>([\s\S]*?)(?=<h[23]|$)",
        re.IGNORECASE,
    )

    for match in heading_pattern.finditer(html):
        heading_html = match.group(1)
        content_html = match.group(2)

        # Clean heading
        heading = re.sub(r"<[^>]+>", "", heading_html).strip().lower()
        if not heading or len(heading) > 80:
            continue

        # Clean content — strip HTML tags, decode entities
        content = re.sub(r"<[^>]+>", " ", content_html)
        content = (
            content.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&nbsp;", " ")
            .replace("&#39;", "'")
            .replace("&quot;", '"')
        )
        content = re.sub(r"\s{3,}", "\n", content)
        content = content.strip()

        # Truncate excessively long sections (FAQ content at end)
        if len(content) > 3000:
            content = content[:3000]

        if content:
            sections[heading] = content

    return sections


def _extract_pack_size(price_text: str) -> str:
    """Extract pack size info from price text."""
    if not price_text:
        return ""
    pack_match = re.search(r"(\d+\s*[x×]\s*\d+|\d+'s?\s*pack|\d+\s*tablet|\d+\s*ml)", price_text, re.IGNORECASE)
    return pack_match.group(0).strip() if pack_match else ""


def _extract_preg_category(text: str) -> str | None:
    """Extract FDA pregnancy category letter from text."""
    if not text:
        return None
    cat_match = re.search(r"\bCategory\s+([ABCDX])\b", text, re.IGNORECASE)
    if cat_match:
        return cat_match.group(1)
    return None


def _text(elem) -> str:
    if elem is None:
        return ""
    return elem.text.strip() if hasattr(elem, "text") and elem.text else ""
