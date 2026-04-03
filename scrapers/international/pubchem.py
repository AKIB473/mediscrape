"""PubChem scraper - 286M+ substances, chemical data. Free PUG-REST API."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from models.drug import Drug
from scrapers.base import BaseAPIScraper

logger = logging.getLogger(__name__)

BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"


class PubChemScraper(BaseAPIScraper):
    name = "pubchem"
    base_url = BASE
    rate_limit = 0.25  # PubChem: 5 requests/second

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Use PubChem's classification to get FDA-approved drug CIDs
        cids = await self._get_drug_cids()
        logger.info(f"PubChem: found {len(cids)} drug CIDs")

        # Process in batches of 50
        batch_size = 50
        for i in range(0, len(cids), batch_size):
            batch = cids[i:i + batch_size]
            try:
                drugs = await self._fetch_batch(batch)
                for drug in drugs:
                    yield drug
            except Exception as e:
                logger.warning(f"PubChem: batch error at {i}: {e}")

    async def _get_drug_cids(self) -> list[int]:
        """Get CIDs of known drugs via PubChem classification."""
        all_cids = []

        # Strategy: search for common drug names to bootstrap CID list
        # PubChem's /compound/name/{name}/cids/JSON is fast for individual lookups
        seed_drugs = [
            "aspirin", "ibuprofen", "acetaminophen", "metformin", "amoxicillin",
            "omeprazole", "atorvastatin", "lisinopril", "amlodipine", "metoprolol",
            "losartan", "simvastatin", "levothyroxine", "azithromycin", "clopidogrel",
            "gabapentin", "sertraline", "fluoxetine", "escitalopram", "duloxetine",
            "prednisone", "tramadol", "furosemide", "albuterol", "pantoprazole",
            "ciprofloxacin", "doxycycline", "cetirizine", "loratadine", "ranitidine",
        ]

        for name in seed_drugs:
            try:
                data = await self.api_get(f"{BASE}/compound/name/{name}/cids/JSON")
                cids = data.get("IdentifierList", {}).get("CID", [])
                all_cids.extend(cids[:3])  # Take top 3 CIDs per drug
            except Exception:
                continue

        # Also try the classification-based approach
        try:
            data = await self.api_get(
                f"{BASE}/compound/name/pharmaceutical/cids/JSON",
                params={"name_type": "word", "MaxRecords": 10000},
            )
            cids = data.get("IdentifierList", {}).get("CID", [])
            all_cids.extend(cids[:5000])
        except Exception:
            pass

        # Deduplicate
        return list(dict.fromkeys(all_cids))

    async def _fetch_batch(self, cids: list[int]) -> list[Drug]:
        cid_str = ",".join(str(c) for c in cids)

        # Get properties (single batch request for all CIDs)
        props = await self.api_get(
            f"{BASE}/compound/cid/{cid_str}/property/"
            "MolecularFormula,MolecularWeight,CanonicalSMILES,InChI,InChIKey,"
            "IUPACName,XLogP,ExactMass,MonoisotopicMass,TPSA,Complexity,"
            "HBondDonorCount,HBondAcceptorCount,RotatableBondCount,"
            "HeavyAtomCount,IsomericSMILES,CovalentUnitCount,Volume3D"
            "/JSON"
        )

        compounds = props.get("PropertyTable", {}).get("Properties", [])

        # Batch fetch synonyms for all CIDs at once
        syn_map: dict[int, list[str]] = {}
        try:
            syn_data = await self.api_get(
                f"{BASE}/compound/cid/{cid_str}/synonyms/JSON"
            )
            for info in syn_data.get("InformationList", {}).get("Information", []):
                syn_map[info.get("CID", 0)] = info.get("Synonym", [])[:50]
        except Exception:
            pass

        drugs = []
        for comp in compounds:
            cid = comp.get("CID")
            synonyms = syn_map.get(cid, [])
            description = None  # Skip per-CID description calls for speed

            drug = Drug(
                source="pubchem",
                source_url=f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
                source_id=str(cid),
                generic_name=comp.get("IUPACName"),
                chemical_name=comp.get("IUPACName"),
                molecular_formula=comp.get("MolecularFormula"),
                molecular_weight=comp.get("MolecularWeight"),
                smiles=comp.get("CanonicalSMILES"),
                inchi=comp.get("InChI"),
                inchi_key=comp.get("InChIKey"),
                pubchem_cid=cid,
                synonyms=synonyms[:50],
                brand_name=synonyms[0] if synonyms else None,
                description=description,
                extra={
                    "xlogp": comp.get("XLogP"),
                    "exact_mass": comp.get("ExactMass"),
                    "monoisotopic_mass": comp.get("MonoisotopicMass"),
                    "tpsa": comp.get("TPSA"),
                    "complexity": comp.get("Complexity"),
                    "hbond_donor_count": comp.get("HBondDonorCount"),
                    "hbond_acceptor_count": comp.get("HBondAcceptorCount"),
                    "rotatable_bond_count": comp.get("RotatableBondCount"),
                    "heavy_atom_count": comp.get("HeavyAtomCount"),
                    "isomeric_smiles": comp.get("IsomericSMILES"),
                    "covalent_unit_count": comp.get("CovalentUnitCount"),
                    "volume_3d": comp.get("Volume3D"),
                },
            )
            drugs.append(drug)

        return drugs
