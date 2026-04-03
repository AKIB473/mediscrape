"""eMC (UK) scraper - medicines.org.uk/emc - 9k+ UK medicines."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class EMCScraper(BaseScrapingScraper):
    name = "emc"
    base_url = "https://www.medicines.org.uk"
    rate_limit = 1.5
    use_stealth = True

    async def scrape_all(self) -> AsyncIterator[Drug]:
        urls = await self._get_all_drug_urls()
        logger.info(f"eMC: found {len(urls)} drug URLs")

        for url in urls:
            try:
                drug = await self._scrape_drug_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"eMC: error scraping {url}: {e}")

    async def _get_all_drug_urls(self) -> list[str]:
        urls = set()

        # eMC browse by letter
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0":
            try:
                page = await self.fetch_page(f"{self.base_url}/emc/browse-medicines/{letter}")
                for link in page.css('a[href*="/emc/product/"], a[href*="/emc/medicine/"]'):
                    href = link.attrib.get("href", "")
                    if href:
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        urls.add(full)
            except Exception:
                pass

        return list(urls)

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        title = _text(page.css_first("h1, .product-name"))
        if not title:
            return None

        # eMC SmPC sections are numbered 1-13
        sections = {}
        for section in page.css(".section, [class*=spc-section]"):
            heading = _text(section.css_first("h2, h3, .section-heading"))
            content = _text(section.css_first(".section-content, p, div"))
            if heading:
                sections[heading.lower()] = content

        # Key fields
        active_substance = sections.get("qualitative and quantitative composition", "")
        pharma_form = sections.get("pharmaceutical form", "")
        therapeutic_indications = sections.get("therapeutic indications", "")
        posology = sections.get("posology and method of administration", "")
        contraindications = sections.get("contraindications", "")
        warnings_text = sections.get("special warnings and precautions for use", "")
        interactions_text = sections.get("interaction with other medicinal products and other forms of interaction", "")
        pregnancy_text = sections.get("fertility, pregnancy and lactation", sections.get("pregnancy and lactation", ""))
        undesirable = sections.get("undesirable effects", "")
        overdose = sections.get("overdose", "")
        pharma_props = sections.get("pharmacological properties", "")
        pharmacodynamics = sections.get("pharmacodynamic properties", "")
        pharmacokinetics = sections.get("pharmacokinetic properties", "")
        preclinical = sections.get("preclinical safety data", "")
        excipients = sections.get("list of excipients", "")
        incompatibilities = sections.get("incompatibilities", "")
        shelf_life = sections.get("shelf life", "")
        storage = sections.get("special precautions for storage", "")
        marketing_auth = sections.get("marketing authorisation holder", "")
        ma_number = sections.get("marketing authorisation number(s)", "")

        manufacturer = None
        if marketing_auth:
            manufacturer = Manufacturer(name=marketing_auth, country="UK")

        return Drug(
            source="emc",
            source_url=url,
            brand_name=title,
            generic_name=active_substance.split("(")[0].strip() if active_substance else "",
            dosage_form=pharma_form,
            indications=_split(therapeutic_indications),
            contraindications=_split(contraindications),
            side_effects=_split(undesirable),
            warnings=_split(warnings_text),
            interactions=_split(interactions_text),
            dosage=posology,
            overdose=overdose,
            pregnancy_category=pregnancy_text,
            pharmacodynamics=pharmacodynamics,
            storage=storage,
            shelf_life=shelf_life,
            manufacturer=manufacturer,
            registration_number=ma_number,
            description=active_substance,
            extra={
                "jsonld": jsonld,
                "smpc_sections": sections,
                "excipients": excipients,
                "incompatibilities": incompatibilities,
                "preclinical_data": preclinical,
                "pharmacokinetics_text": pharmacokinetics,
                "pharma_properties": pharma_props,
            },
        )


def _text(elem) -> str:
    if elem is None:
        return ""
    return elem.text.strip() if hasattr(elem, "text") and elem.text else ""


def _split(text: str) -> list[str]:
    if not text:
        return []
    return [i.strip() for i in re.split(r"[•\n;]", text) if i.strip()]
