"""OpenFDA scraper - US drugs, adverse events, labeling, recalls. No API key needed."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from models.drug import Drug, Manufacturer, DrugPrice
from scrapers.base import BaseAPIScraper

logger = logging.getLogger(__name__)

BASE = "https://api.fda.gov"


class OpenFDAScraper(BaseAPIScraper):
    name = "openfda"
    base_url = BASE
    rate_limit = 0.5  # FDA allows 40 req/min without key

    async def scrape_all(self) -> AsyncIterator[Drug]:
        skip = 0
        limit = 100

        while True:
            try:
                data = await self.api_get(
                    f"{BASE}/drug/label.json",
                    params={"limit": limit, "skip": skip},
                )
            except Exception as e:
                logger.error(f"OpenFDA request failed at skip={skip}: {e}")
                break

            results = data.get("results", [])
            if not results:
                break

            for item in results:
                drug = self._parse_label(item)
                if drug:
                    yield drug

            skip += limit
            total = data.get("meta", {}).get("results", {}).get("total", 0)
            if skip >= total:
                break

    def _parse_label(self, item: dict) -> Drug | None:
        openfda = item.get("openfda", {})
        brand = _first(openfda.get("brand_name", []))
        generic = _first(openfda.get("generic_name", []))
        if not brand and not generic:
            return None

        manufacturers = []
        for mfr in openfda.get("manufacturer_name", []):
            manufacturers.append(Manufacturer(name=mfr))

        return Drug(
            source="openfda",
            source_url=f"https://api.fda.gov/drug/label.json",
            source_id=item.get("id") or _first(openfda.get("spl_id", [])),
            brand_name=brand,
            generic_name=generic,
            drug_class=_first(openfda.get("pharm_class_epc", [])),
            pharmacological_class=_first(openfda.get("pharm_class_moa", [])),
            therapeutic_class=_first(openfda.get("pharm_class_cs", [])),
            dosage_form=_first(openfda.get("dosage_form", [])),
            route=_first(openfda.get("route", [])),
            strength=_first(item.get("active_ingredient", [])),
            manufacturer=manufacturers[0] if manufacturers else None,
            manufacturers=manufacturers,
            rxcui=_first(openfda.get("rxcui", [])),
            unii=_first(openfda.get("unii", [])),
            ndc=openfda.get("product_ndc", []),
            indications=item.get("indications_and_usage", []),
            contraindications=item.get("contraindications", []),
            warnings=item.get("warnings", []),
            precautions=item.get("precautions", []),
            adverse_reactions=item.get("adverse_reactions", []),
            drug_interactions=[
                {"description": i} for i in item.get("drug_interactions", [])
            ],
            dosage=_first(item.get("dosage_and_administration", [])),
            mechanism_of_action=_first(item.get("mechanism_of_action", [])),
            pharmacodynamics=_first(item.get("pharmacodynamics", [])),
            pharmacokinetics={
                "description": _first(item.get("clinical_pharmacology", []))
            } if item.get("clinical_pharmacology") else None,
            pregnancy_category=_first(item.get("pregnancy", [])),
            lactation=_first(item.get("nursing_mothers", [])),
            boxed_warning=_first(item.get("boxed_warning", [])),
            black_box_warning=bool(item.get("boxed_warning")),
            overdose=_first(item.get("overdosage", [])),
            storage=_first(item.get("storage_and_handling", [])),
            description=_first(item.get("description", [])),
            categories=openfda.get("pharm_class_epc", []),
            extra={
                "spl_id": _first(openfda.get("spl_id", [])),
                "spl_set_id": _first(openfda.get("spl_set_id", [])),
                "application_number": _first(openfda.get("application_number", [])),
                "product_type": _first(openfda.get("product_type", [])),
                "substance_name": openfda.get("substance_name", []),
                "clinical_pharmacology": item.get("clinical_pharmacology", []),
                "geriatric_use": item.get("geriatric_use", []),
                "pediatric_use": item.get("pediatric_use", []),
                "abuse": item.get("drug_abuse_and_dependence", []),
                "how_supplied": item.get("how_supplied", []),
                "information_for_patients": item.get("information_for_patients", []),
                "laboratory_tests": item.get("laboratory_tests", []),
                "carcinogenesis": item.get("carcinogenesis_and_mutagenesis_and_impairment_of_fertility", []),
                "effective_time": item.get("effective_time"),
                "version": item.get("version"),
            },
        )


def _first(lst: list) -> str | None:
    return lst[0] if lst else None
