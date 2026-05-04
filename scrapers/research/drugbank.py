"""DrugBank scraper - go.drugbank.com - 4,563 approved + 6,231 investigational drugs."""

from __future__ import annotations

import logging
import os
import re
from typing import AsyncIterator

from models.drug import Drug, Manufacturer
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class DrugBankScraper(BaseScrapingScraper):
    name = "drugbank"
    base_url = "https://go.drugbank.com"
    rate_limit = 3.0  # DrugBank is strict; 3 s between requests
    use_stealth = True

    # Max pages to paginate — DrugBank has ~100 pages of approved drugs.
    # Keep this low in default (non-fullscrape) mode to respect rate limits.
    _default_max_pages = int(os.getenv("DRUGBANK_MAX_PAGES", "100"))

    async def scrape_all(self) -> AsyncIterator[Drug]:
        urls = await self._get_drug_urls()
        logger.info(f"DrugBank: found {len(urls)} drug URLs")

        for url in urls:
            try:
                drug = await self._scrape_drug_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"DrugBank: error scraping {url}: {e}")

    async def _get_drug_urls(self) -> list[str]:
        urls: dict[str, None] = {}  # ordered set via dict

        # DrugBank lists approved drugs at /drugs?approved=1, sorted by name.
        # Each page has ~25 drugs. Default: paginate up to _default_max_pages.
        for page_num in range(1, self._default_max_pages + 1):
            try:
                page = await self.fetch_page(
                    f"{self.base_url}/drugs",
                    # StealthyFetcher.fetch() passes kwargs to playwright; pass params via URL
                )
                # Attempt with query string in URL directly
                page = await self.fetch_page(
                    f"{self.base_url}/drugs?page={page_num}&approved=1"
                )
                found = 0
                for link in page.css('a[href*="/drugs/DB"]'):
                    href = link.attrib.get("href", "")
                    if href and re.search(r"/drugs/DB\d+", href):
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        # Normalise: strip query string
                        full = full.split("?")[0]
                        if full not in urls:
                            urls[full] = None
                            found += 1
                if found == 0:
                    logger.debug(f"DrugBank: no new URLs on page {page_num}, stopping")
                    break
                logger.debug(f"DrugBank: page {page_num} → {found} new URLs ({len(urls)} total)")
            except Exception as e:
                logger.warning(f"DrugBank: error on page {page_num}: {e}")
                break

        return list(urls.keys())

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        title = _text(page.css_first("h1"))
        if not title:
            return None

        # DrugBank has a structured layout with dt/dd pairs
        fields = {}
        for dt in page.css("dt"):
            key = _text(dt).lower().strip()
            dd = dt.css_first("+ dd")
            if dd:
                # Check for lists
                items = dd.css("li, a")
                if items:
                    fields[key] = [_text(i) for i in items]
                else:
                    fields[key] = _text(dd)

        # Extract drugbank ID from URL
        db_id = ""
        match = re.search(r"DB\d+", url)
        if match:
            db_id = match.group()

        # Parse targets
        targets = []
        target_section = page.css_first("#targets, .bond-table")
        if target_section:
            for row in target_section.css("tr"):
                target_name = _text(row.css_first("td:first-child, .bond-name"))
                if target_name:
                    targets.append(target_name)

        # Parse interactions
        interactions = []
        int_section = page.css_first("#interactions")
        if int_section:
            for row in int_section.css("tr"):
                drug_name = _text(row.css_first("td:first-child"))
                description = _text(row.css_first("td:nth-child(2)"))
                if drug_name:
                    interactions.append({"drug": drug_name, "description": description})

        # Parse pathways
        pathways = []
        path_section = page.css_first("#pathways")
        if path_section:
            for link in path_section.css("a"):
                pathways.append(_text(link))

        def _get(key: str, default=""):
            v = fields.get(key, default)
            return v if isinstance(v, str) else ", ".join(v) if isinstance(v, list) else str(v)

        def _get_list(key: str) -> list[str]:
            v = fields.get(key, [])
            if isinstance(v, list):
                return v
            return [v] if v else []

        return Drug(
            source="drugbank",
            source_url=url,
            source_id=db_id,
            drugbank_id=db_id,
            brand_name=title,
            generic_name=_get("generic name"),
            synonyms=_get_list("synonyms"),
            drug_class=_get("drug class") or _get("pharmacological class"),
            therapeutic_class=_get("therapeutic class"),
            pharmacological_class=_get("pharmacological class"),
            atc_code=_get("atc codes"),
            chemical_name=_get("iupac name") or _get("chemical name"),
            molecular_formula=_get("molecular formula") or _get("chemical formula"),
            molecular_weight=_float(_get("molecular weight") or _get("average mass")),
            cas_number=_get("cas number") or _get("cas registry number"),
            smiles=_get("smiles"),
            inchi=_get("inchi"),
            inchi_key=_get("inchi key") or _get("inchikey"),
            unii=_get("unii"),
            rxcui=_get("rxcui"),
            dosage_form=_get("dosage form") or _get("dosage forms"),
            strength=_get("strength"),
            route=_get("route of administration") or _get("route"),
            manufacturer=Manufacturer(name=_get("manufacturer")) if _get("manufacturer") else None,
            indications=_get_list("indication") or [_get("indication")],
            contraindications=_get_list("contraindications"),
            side_effects=_get_list("adverse effects") or _get_list("side effects"),
            warnings=_get_list("warnings"),
            drug_interactions=interactions,
            food_interactions=_get_list("food interactions"),
            mechanism_of_action=_get("mechanism of action") or _get("pharmacodynamics"),
            pharmacodynamics=_get("pharmacodynamics"),
            absorption=_get("absorption"),
            distribution=_get("volume of distribution"),
            metabolism=_get("metabolism"),
            elimination=_get("route of elimination"),
            half_life=_get("half-life") or _get("half life"),
            bioavailability=_get("bioavailability"),
            protein_binding=_get("protein binding"),
            volume_of_distribution=_get("volume of distribution"),
            clearance=_get("clearance"),
            pregnancy_category=_get("pregnancy category"),
            description=_get("summary") or _get("description") or _get("background"),
            categories=_get_list("categories"),
            extra={
                "jsonld": jsonld,
                "state": _get("state"),
                "type": _get("type"),
                "groups": _get_list("groups"),
                "targets": targets,
                "pathways": pathways,
                "enzymes": _get_list("enzymes"),
                "carriers": _get_list("carriers"),
                "transporters": _get_list("transporters"),
                "affected_organisms": _get_list("affected organisms"),
                "pka": _get("pka"),
                "logp": _get("logp"),
                "logs": _get("logs"),
                "water_solubility": _get("water solubility"),
                "toxicity": _get("toxicity"),
                "experimental_properties": _get("experimental properties"),
                "external_links": _get_list("external links"),
                "patents": _get_list("patents"),
                "all_fields": {k: v for k, v in fields.items()},
            },
        )


def _text(elem) -> str:
    if elem is None:
        return ""
    return elem.text.strip() if hasattr(elem, "text") and elem.text else ""


def _float(v: str) -> float | None:
    if not v:
        return None
    nums = re.findall(r"[\d.]+", v)
    if nums:
        try:
            return float(nums[0])
        except ValueError:
            return None
    return None
