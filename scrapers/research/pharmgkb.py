"""PharmGKB/ClinPGx scraper - Pharmacogenomics data.

Note: PharmGKB has rebranded to ClinPGx (clinpgx.org).
API still available at api.pharmgkb.org (redirects to api.clinpgx.org).
Rate limit: 2 requests/second. License: CC BY-SA 4.0.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from models.drug import Drug
from scrapers.base import BaseAPIScraper

logger = logging.getLogger(__name__)

# Try ClinPGx first, fallback to PharmGKB
BASE = "https://api.pharmgkb.org/v1/data"


class PharmGKBScraper(BaseAPIScraper):
    name = "pharmgkb"
    base_url = BASE
    rate_limit = 0.5

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # PharmGKB API: use types=Drug to get all drug chemicals
        data = await self.api_get(
            f"{BASE}/chemical",
            params={"types": "Drug", "view": "max"},
        )

        items = data.get("data", [])
        logger.info(f"PharmGKB: got {len(items)} drugs from API")

        for item in items:
            drug = self._parse_chemical(item)
            if drug:
                yield drug

    def _parse_chemical(self, item: dict) -> Drug | None:
        name = item.get("name")
        if not name:
            return None

        pharmgkb_id = item.get("id", "")

        # Cross references
        xrefs = item.get("crossReferences", [])
        drugbank_id = None
        pubchem_cid = None
        rxcui = None
        cas = None
        chembl_id = None

        for xref in xrefs:
            resource = xref.get("resource", "")
            xid = xref.get("resourceId", "")
            if resource == "DrugBank":
                drugbank_id = xid
            elif resource == "PubChem Compound":
                try:
                    pubchem_cid = int(xid)
                except (ValueError, TypeError):
                    pass
            elif resource == "RxNorm":
                rxcui = xid
            elif resource == "CAS":
                cas = xid
            elif resource == "ChEMBL":
                chembl_id = xid

        # Dosing guidelines
        guidelines = item.get("guideline", [])
        guideline_data = []
        for g in guidelines:
            guideline_data.append({
                "id": g.get("id"),
                "name": g.get("name"),
                "source": g.get("source"),
            })

        # Clinical annotations
        annotations = item.get("clinicalAnnotation", [])

        return Drug(
            source="pharmgkb",
            source_url=f"https://www.pharmgkb.org/chemical/{pharmgkb_id}",
            source_id=pharmgkb_id,
            generic_name=name,
            synonyms=item.get("alternateNames", []),
            drug_class=item.get("type"),
            drugbank_id=drugbank_id,
            pubchem_cid=pubchem_cid,
            rxcui=rxcui,
            cas_number=cas,
            chembl_id=chembl_id,
            atc_code=item.get("atcCode"),
            smiles=item.get("smiles"),
            inchi=item.get("inchi"),
            categories=[item["type"]] if item.get("type") else [],
            extra={
                "pharmgkb_id": pharmgkb_id,
                "dosing_guidelines": guideline_data,
                "clinical_annotations_count": len(annotations),
                "has_rx_annotation": item.get("hasRxAnnotation", False),
                "has_dosing_info": item.get("hasDosing", False),
                "has_prescribing_info": item.get("hasPrescribingInfo", False),
                "top_clinical_annotation_level": item.get("topClinicalAnnotationLevel"),
                "top_fda_label_testing_level": item.get("topFdaLabelTestingLevel"),
                "top_cpic_level": item.get("topCpicLevel"),
                "top_dpwg_level": item.get("topDpwgLevel"),
                "terms": item.get("terms", []),
                "mesh_id": item.get("meshId"),
                "generic_names": item.get("genericNames", []),
                "trade_names": item.get("tradeNames", []),
                "brand_mixtures": item.get("brandMixtures", []),
                "cross_references": xrefs,
            },
        )
