"""Drugs.com scraper - 24k+ drugs, interactions, pill ID."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class DrugsComScraper(BaseScrapingScraper):
    name = "drugs_com"
    base_url = "https://www.drugs.com"
    rate_limit = 2.0  # Be polite
    use_stealth = True

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Drugs.com has an A-Z index at /drug_information.html
        urls = await self._get_all_drug_urls()
        logger.info(f"Drugs.com: found {len(urls)} drug URLs")

        for url in urls:
            try:
                drug = await self._scrape_drug_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"Drugs.com: error scraping {url}: {e}")

    async def _get_all_drug_urls(self) -> list[str]:
        urls = set()

        # A-Z pages
        for letter in "abcdefghijklmnopqrstuvwxyz0":
            try:
                page = await self.fetch_page(f"{self.base_url}/alpha/{letter}.html")
                for link in page.css('a[href$=".html"]'):
                    href = link.attrib.get("href", "")
                    if href and not any(skip in href for skip in ["/alpha/", "/drug_information", "/support", "/pro/"]):
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        urls.add(full)
            except Exception:
                pass

        return list(urls)

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        title = _text(page.css_first("h1"))
        if not title:
            return None

        # Extract generic name from the header area
        generic_elem = page.css_first(".drug-subtitle, .ddc-pronunciation, [class*=generic]")
        generic_name = _text(generic_elem)

        # Parse JSON-LD Drug/MedicalEntity if present
        for ld in jsonld:
            if ld.get("@type") in ("Drug", "MedicalEntity", "MedicalWebPage"):
                return self._parse_jsonld_drug(ld, url, page)

        # Extract sections
        sections = {}
        for h2 in page.css("h2, h3"):
            key = _text(h2).lower()
            content_parts = []
            sibling = h2
            while True:
                sibling = sibling.css_first("+ p, + ul, + ol, + div")
                if sibling is None:
                    break
                t = _text(sibling)
                if t:
                    content_parts.append(t)
                if len(content_parts) > 20:
                    break
            if content_parts:
                sections[key] = "\n".join(content_parts)

        # Extract side effects specifically
        side_effects = []
        se_section = page.css_first("#sideEffects, .side-effects-section, [id*=side]")
        if se_section:
            for li in se_section.css("li"):
                t = _text(li)
                if t:
                    side_effects.append(t)

        # Drug class / category
        drug_class = _text(page.css_first(".drug-class, [class*=drug-class]"))

        # Pregnancy category
        pregnancy = ""
        for key, val in sections.items():
            if "pregnancy" in key:
                pregnancy = val
                break

        return Drug(
            source="drugs_com",
            source_url=url,
            brand_name=title,
            generic_name=generic_name,
            drug_class=drug_class,
            indications=_split(sections.get("uses", sections.get("what is", ""))),
            contraindications=_split(sections.get("before taking", "")),
            side_effects=side_effects or _split(sections.get("side effects", "")),
            warnings=_split(sections.get("warnings", "")),
            interactions=_split(sections.get("interactions", sections.get("drug interactions", ""))),
            dosage=sections.get("dosage", sections.get("dosing information", "")),
            overdose=sections.get("overdose", sections.get("what happens if i overdose", "")),
            storage=sections.get("storage", ""),
            pregnancy_category=pregnancy,
            mechanism_of_action=sections.get("mechanism of action", sections.get("how it works", "")),
            description=sections.get("what is", ""),
            extra={
                "jsonld": jsonld,
                "sections": sections,
                "availability": sections.get("availability", ""),
                "missed_dose": sections.get("missed dose", sections.get("what happens if i miss a dose", "")),
            },
        )

    def _parse_jsonld_drug(self, ld: dict, url: str, page) -> Drug:
        return Drug(
            source="drugs_com",
            source_url=url,
            brand_name=ld.get("name") or ld.get("proprietaryName"),
            generic_name=ld.get("nonProprietaryName") or ld.get("activeIngredient"),
            drug_class=ld.get("drugClass"),
            dosage_form=ld.get("dosageForm"),
            route=ld.get("administrationRoute"),
            description=ld.get("description"),
            warnings=[ld["warning"]] if ld.get("warning") else [],
            indications=[ld["indication"]] if isinstance(ld.get("indication"), str) else [],
            mechanism_of_action=ld.get("mechanismOfAction"),
            side_effects=[ld["adverseOutcome"]] if isinstance(ld.get("adverseOutcome"), str) else [],
            extra={
                "jsonld": ld,
                "legal_status": ld.get("legalStatus"),
                "is_proprietary": ld.get("isProprietary"),
                "clinical_pharmacology": ld.get("clinicalPharmacology"),
                "food_warning": ld.get("foodWarning"),
                "pregnancy_warning": ld.get("pregnancyWarning"),
                "alcohol_warning": ld.get("alcoholWarning"),
                "breastfeeding_warning": ld.get("breastfeedingWarning"),
                "overdosage": ld.get("overdosage"),
                "prescribing_info": ld.get("prescribingInfo"),
                "related_drug": ld.get("relatedDrug"),
                "available_strength": ld.get("availableStrength"),
            },
        )


def _text(elem) -> str:
    if elem is None:
        return ""
    return elem.text.strip() if hasattr(elem, "text") and elem.text else ""


def _split(text: str) -> list[str]:
    if not text:
        return []
    return [i.strip() for i in re.split(r"[•\n]", text) if i.strip()]
