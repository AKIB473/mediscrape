"""KEGG DRUG scraper - Approved drugs (Japan/US/EU), pathways. Free REST API."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug
from scrapers.base import BaseAPIScraper

logger = logging.getLogger(__name__)

BASE = "https://rest.kegg.jp"


class KEGGScraper(BaseAPIScraper):
    name = "kegg"
    base_url = BASE
    rate_limit = 0.35  # Be polite to KEGG

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Get list of all drug entries
        text = await self.api_get_text(f"{BASE}/list/drug")
        entries = []
        for line in text.strip().split("\n"):
            parts = line.split("\t")
            if len(parts) >= 2:
                drug_id = parts[0].replace("dr:", "")
                entries.append(drug_id)

        logger.info(f"KEGG: found {len(entries)} drug entries")

        for drug_id in entries:
            try:
                drug = await self._fetch_drug(drug_id)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"KEGG: error fetching {drug_id}: {e}")

    async def _fetch_drug(self, drug_id: str) -> Drug | None:
        text = await self.api_get_text(f"{BASE}/get/{drug_id}")
        fields = self._parse_kegg_flat(text)

        if not fields:
            return None

        names = fields.get("NAME", "").split(";")
        names = [n.strip().rstrip(";") for n in names if n.strip()]

        # Parse formula
        formula = fields.get("FORMULA")
        mol_weight = None
        mw_str = fields.get("MOL_WEIGHT") or fields.get("EXACT_MASS")
        if mw_str:
            try:
                mol_weight = float(mw_str.strip())
            except ValueError:
                pass

        # Parse drug classes and targets
        classes = [c.strip() for c in fields.get("CLASS", "").split(";") if c.strip()]
        targets = [t.strip() for t in fields.get("TARGET", "").split("\n") if t.strip()]
        pathways = [p.strip() for p in fields.get("PATHWAY", "").split("\n") if p.strip()]

        # Parse external IDs
        dblinks = fields.get("DBLINKS", "")
        cas = _extract_dblink(dblinks, "CAS")
        pubchem_sid = _extract_dblink(dblinks, "PubChem")
        chembl = _extract_dblink(dblinks, "ChEMBL")
        drugbank = _extract_dblink(dblinks, "DrugBank")

        return Drug(
            source="kegg",
            source_url=f"https://www.kegg.jp/entry/{drug_id}",
            source_id=drug_id,
            brand_name=names[0] if names else None,
            generic_name=names[1] if len(names) > 1 else (names[0] if names else None),
            synonyms=names[1:] if len(names) > 1 else [],
            chemical_name=fields.get("CHEMICAL_NAME"),
            molecular_formula=formula,
            molecular_weight=mol_weight,
            cas_number=cas,
            chembl_id=chembl,
            drugbank_id=drugbank,
            therapeutic_class=classes[0] if classes else None,
            categories=classes,
            dosage_form=fields.get("DOSAGE_FORM"),
            route=fields.get("ROUTE"),
            indications=[fields.get("ACTIVITY", "")] if fields.get("ACTIVITY") else [],
            description=fields.get("REMARK"),
            extra={
                "kegg_id": drug_id,
                "type": fields.get("TYPE"),
                "component": fields.get("COMPONENT"),
                "structure_map": fields.get("STR_MAP"),
                "targets": targets,
                "pathways": pathways,
                "metabolism": fields.get("METABOLISM"),
                "interaction": fields.get("INTERACTION"),
                "sequence": fields.get("SEQUENCE"),
                "source": fields.get("SOURCE"),
                "product": fields.get("PRODUCT"),
                "pubchem_sid": pubchem_sid,
                "dblinks_raw": dblinks,
                "efficacy": fields.get("EFFICACY"),
                "disease": fields.get("DISEASE"),
                "comment": fields.get("COMMENT"),
                "brite": fields.get("BRITE"),
                "atoms": fields.get("ATOM"),
                "bonds": fields.get("BOND"),
            },
        )

    def _parse_kegg_flat(self, text: str) -> dict:
        """Parse KEGG flat file format."""
        fields = {}
        current_key = None
        current_value = []

        for line in text.split("\n"):
            if line.startswith("///"):
                break
            if line and not line[0].isspace() and line[:12].strip():
                if current_key:
                    fields[current_key] = "\n".join(current_value).strip()
                key_part = line[:12].strip()
                val_part = line[12:].strip()
                current_key = key_part
                current_value = [val_part]
            elif current_key:
                current_value.append(line.strip())

        if current_key:
            fields[current_key] = "\n".join(current_value).strip()

        return fields


def _extract_dblink(dblinks: str, db_name: str) -> str | None:
    for line in dblinks.split("\n"):
        if db_name + ":" in line:
            parts = line.split(":")
            if len(parts) >= 2:
                return parts[-1].strip().split()[0]
    return None
