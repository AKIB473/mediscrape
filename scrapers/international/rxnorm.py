"""RxNorm/RxNav scraper - Drug names, interactions, drug classes. Free REST API."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from models.drug import Drug
from scrapers.base import BaseAPIScraper

logger = logging.getLogger(__name__)

BASE = "https://rxnav.nlm.nih.gov/REST"


class RxNormScraper(BaseAPIScraper):
    name = "rxnorm"
    base_url = BASE
    rate_limit = 0.25  # NLM is generous but be polite

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Get all drug concepts.
        # RxNav /allconcepts.json requires tty as a space-separated query param.
        # httpx params= encodes spaces as %20 which the API accepts; avoid + encoding.
        # Fetch each tty type separately to stay within response size limits.
        all_concepts: list[dict] = []
        for tty in ["BN", "IN", "SBD", "SCD"]:
            try:
                data = await self.api_get(
                    f"{BASE}/allconcepts.json",
                    params={"tty": tty},
                )
                batch = data.get("minConceptGroup", {}).get("minConcept", [])
                logger.info(f"RxNorm: {tty} → {len(batch)} concepts")
                all_concepts.extend(batch)
            except Exception as e:
                logger.warning(f"RxNorm: failed to get tty={tty}: {e}")
        concepts = all_concepts
        logger.info(f"RxNorm: {len(concepts)} total concepts")

        for concept in concepts:
            rxcui = concept.get("rxcui")
            name = concept.get("name")
            tty = concept.get("tty")
            if not rxcui:
                continue

            try:
                drug = await self._fetch_drug_details(rxcui, name, tty)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"RxNorm: error fetching {rxcui}: {e}")

    async def _fetch_drug_details(self, rxcui: str, name: str, tty: str) -> Drug | None:
        # Get properties
        props = await self.api_get(f"{BASE}/rxcui/{rxcui}/allProperties.json", params={"prop": "all"})
        prop_list = props.get("propConceptGroup", {}).get("propConcept", [])
        prop_map = {}
        for p in prop_list:
            prop_map.setdefault(p.get("propName"), []).append(p.get("propValue"))

        # Get related concepts (ingredients, brands, etc.)
        related = await self.api_get(f"{BASE}/rxcui/{rxcui}/allrelated.json")
        related_groups = related.get("allRelatedGroup", {}).get("conceptGroup", [])
        ingredients = []
        brands = []
        for group in related_groups:
            for concept in group.get("conceptProperties", []):
                if group.get("tty") == "IN":
                    ingredients.append(concept.get("name"))
                elif group.get("tty") == "BN":
                    brands.append(concept.get("name"))

        # Get drug classes
        classes_data = await self.api_get(f"{BASE}/rxclass/class/byRxcui.json", params={"rxcui": rxcui})
        drug_classes = []
        class_entries = classes_data.get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", [])
        for entry in class_entries:
            cls_info = entry.get("rxclassMinConceptItem", {})
            drug_classes.append({
                "name": cls_info.get("className"),
                "type": cls_info.get("classType"),
                "id": cls_info.get("classId"),
            })

        # Get NDCs
        ndc_data = await self.api_get(f"{BASE}/rxcui/{rxcui}/ndcs.json")
        ndcs = ndc_data.get("ndcGroup", {}).get("ndcList", {}).get("ndc", [])

        generic_name = ingredients[0] if ingredients else None
        brand_name = brands[0] if brands else (name if tty == "BN" else None)

        return Drug(
            source="rxnorm",
            source_url=f"https://mor.nlm.nih.gov/RxNav/search?searchBy=RXCUI&searchTerm={rxcui}",
            source_id=rxcui,
            brand_name=brand_name,
            generic_name=generic_name or name,
            rxcui=rxcui,
            ndc=ndcs,
            dosage_form=_first(prop_map.get("DOSAGE_FORM", [])),
            strength=_first(prop_map.get("AVAILABLE_STRENGTH", [])),
            route=_first(prop_map.get("ROUTE", [])),
            atc_code=_first(prop_map.get("ATC", [])),
            unii=_first(prop_map.get("UNII_CODE", [])),
            synonyms=prop_map.get("RxNorm Synonym", []),
            categories=[c["name"] for c in drug_classes if c.get("name")],
            extra={
                "tty": tty,
                "ingredients": ingredients,
                "brand_names": brands,
                "drug_classes": drug_classes,
                "properties": {k: v for k, v in prop_map.items()},
                "quantity_factor": _first(prop_map.get("QUANTITY_FACTOR", [])),
                "suppress": _first(prop_map.get("SUPPRESS", [])),
                "prescribable": _first(prop_map.get("PRESCRIBABLE", [])),
            },
        )


def _first(lst: list) -> str | None:
    return lst[0] if lst else None
