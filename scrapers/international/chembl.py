"""ChEMBL scraper - 1.6M compounds, 14M bioactivities. Free REST API, CC license."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from models.drug import Drug, Manufacturer
from scrapers.base import BaseAPIScraper

logger = logging.getLogger(__name__)

BASE = "https://www.ebi.ac.uk/chembl/api/data"


class ChEMBLScraper(BaseAPIScraper):
    name = "chembl"
    base_url = BASE
    rate_limit = 0.2
    headers = {"Accept": "application/json"}

    async def scrape_all(self) -> AsyncIterator[Drug]:
        offset = 0
        limit = 100

        while True:
            data = await self.api_get(
                f"{BASE}/molecule",
                params={
                    "max_phase": 4,  # Approved drugs
                    "limit": limit,
                    "offset": offset,
                    "format": "json",
                },
            )
            molecules = data.get("molecules", [])
            if not molecules:
                break

            for mol in molecules:
                drug = self._parse_molecule(mol)
                if drug:
                    yield drug

            page_meta = data.get("page_meta", {})
            if not page_meta.get("next"):
                break
            offset += limit

    def _parse_molecule(self, mol: dict) -> Drug | None:
        chembl_id = mol.get("molecule_chembl_id")
        if not chembl_id:
            return None

        props = mol.get("molecule_properties", {}) or {}
        structures = mol.get("molecule_structures", {}) or {}
        synonyms_list = mol.get("molecule_synonyms", []) or []
        hierarchy = mol.get("molecule_hierarchy", {}) or {}
        xrefs = mol.get("cross_references", []) or []

        # Extract brand names and synonyms
        brand_names = []
        inn_names = []
        all_synonyms = []
        for syn in synonyms_list:
            name = syn.get("molecule_synonym")
            syn_type = syn.get("syn_type", "")
            all_synonyms.append(name)
            if syn_type == "TRADE_NAME":
                brand_names.append(name)
            elif syn_type in ("INN", "USAN", "BAN"):
                inn_names.append(name)

        # Cross references
        drugbank_ids = []
        pubchem_cids = []
        for xref in xrefs:
            src = xref.get("xref_src")
            xid = xref.get("xref_id")
            if src == "DrugBank" and xid:
                drugbank_ids.append(xid)
            elif src == "PubChem" and xid:
                pubchem_cids.append(xid)

        return Drug(
            source="chembl",
            source_url=f"https://www.ebi.ac.uk/chembl/compound_report_card/{chembl_id}/",
            source_id=chembl_id,
            brand_name=brand_names[0] if brand_names else None,
            generic_name=inn_names[0] if inn_names else mol.get("pref_name"),
            chembl_id=chembl_id,
            drugbank_id=drugbank_ids[0] if drugbank_ids else None,
            pubchem_cid=int(pubchem_cids[0]) if pubchem_cids else None,
            synonyms=all_synonyms,
            chemical_name=mol.get("pref_name"),
            molecular_formula=props.get("full_molformula"),
            molecular_weight=_float(props.get("full_mwt")),
            smiles=structures.get("canonical_smiles"),
            inchi=structures.get("standard_inchi"),
            inchi_key=structures.get("standard_inchi_key"),
            therapeutic_class=mol.get("therapeutic_flag_description"),
            otc=None,
            description=mol.get("description"),
            extra={
                "molecule_type": mol.get("molecule_type"),
                "max_phase": mol.get("max_phase"),
                "oral": mol.get("oral"),
                "parenteral": mol.get("parenteral"),
                "topical": mol.get("topical"),
                "black_box_warning": mol.get("black_box_warning"),
                "chirality": mol.get("chirality"),
                "prodrug": mol.get("prodrug"),
                "natural_product": mol.get("natural_product"),
                "first_approval": mol.get("first_approval"),
                "indication_class": mol.get("indication_class"),
                "withdrawn_flag": mol.get("withdrawn_flag"),
                "withdrawn_year": mol.get("withdrawn_year"),
                "withdrawn_reason": mol.get("withdrawn_reason"),
                "withdrawn_country": mol.get("withdrawn_country"),
                "availability_type": mol.get("availability_type"),
                "alogp": props.get("alogp"),
                "psa": props.get("psa"),
                "hba": props.get("hba"),
                "hbd": props.get("hbd"),
                "num_ro5_violations": props.get("num_ro5_violations"),
                "ro3_pass": props.get("ro3_pass"),
                "aromatic_rings": props.get("aromatic_rings"),
                "heavy_atoms": props.get("heavy_atoms"),
                "rtb": props.get("rtb"),
                "qed_weighted": props.get("qed_weighted"),
                "cx_logp": props.get("cx_logp"),
                "cx_logd": props.get("cx_logd"),
                "molecular_species": props.get("molecular_species"),
                "hierarchy": hierarchy,
                "brand_names": brand_names,
                "inn_names": inn_names,
                "cross_references": xrefs,
            },
        )


def _float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
