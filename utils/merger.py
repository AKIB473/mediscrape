"""
Drug data merger.

Loads raw drug records from all scraped source directories, normalises them,
groups duplicates together by canonical id, and produces a list of
``MergedDrug`` instances ready to be persisted.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models.merged import DrugPrice, MergedDrug
from utils.normalizer import (
    drug_canonical_id,
    normalize_brand_name,
    normalize_dosage_form,
    normalize_generic_name,
    normalize_manufacturer,
    normalize_strength,
)

logger = logging.getLogger(__name__)

# Sources whose clinical / chemistry data is considered most trustworthy.
PRIORITY_SOURCES = ['medex', 'drugbank', 'pubchem', 'chembl', 'rxnorm', 'openfda', 'dailymed']
# BD price sources
BD_PRICE_SOURCES = [
    'medex', 'arogga', 'osudpotro', 'medeasy', 'lazzpharma',
    'bdmedex', 'bddrugs', 'bddrugstore', 'dims',
]


# ─────────────────────────────────────────────────────────────────────────────
# Loading
# ─────────────────────────────────────────────────────────────────────────────

def load_all_raw_drugs(data_dir: Path) -> list[dict]:
    """
    Walk ``data_dir`` and load every ``drugs.json`` file found in immediate
    sub-directories.  Each record is annotated with a ``'_source'`` key equal
    to the sub-directory name so the merger can track provenance.

    Parameters
    ----------
    data_dir:
        Root data directory (e.g. ``Path("data")``).

    Returns
    -------
    list[dict]
        Flat list of all raw drug dicts, each with ``_source`` injected.
    """
    all_drugs: list[dict] = []
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        logger.warning('data_dir %s does not exist; returning empty list', data_dir)
        return all_drugs

    for source_dir in sorted(data_dir.iterdir()):
        if not source_dir.is_dir():
            continue
        drugs_file = source_dir / 'drugs.json'
        if not drugs_file.exists():
            continue
        source_name = source_dir.name
        try:
            raw = json.loads(drugs_file.read_bytes())
        except Exception as exc:
            logger.error('Failed to load %s: %s', drugs_file, exc)
            continue

        if not isinstance(raw, list):
            logger.warning('%s: expected a JSON array, got %s', drugs_file, type(raw))
            continue

        for rec in raw:
            if isinstance(rec, dict):
                rec['_source'] = source_name
                all_drugs.append(rec)

        logger.info('Loaded %d records from %s', len(raw), source_name)

    logger.info('Total raw records loaded: %d', len(all_drugs))
    return all_drugs


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _coerce_list(value: Any) -> list[str]:
    """Return a flat list of non-empty strings from a variety of inputs."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif isinstance(item, dict):
                # Try common dict fields
                for key in ('name', 'text', 'description', 'value'):
                    if key in item and isinstance(item[key], str) and item[key].strip():
                        result.append(item[key].strip())
                        break
        return result
    return []


def _dedup_list(items: list[str]) -> list[str]:
    """Return deduplicated list preserving insertion order (case-insensitive)."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def pick_best(
    values: list[str],
    priority_sources: list[str],
    source_map: dict[str, str],
) -> str | None:
    """
    Choose the most informative non-empty string from ``values``.

    Selection strategy:

    1. Prefer values whose source appears in ``priority_sources`` (in priority
       order).
    2. Among equal-priority candidates, prefer the longest value (more detail).
    3. Fall back to the longest value regardless of source.

    Parameters
    ----------
    values:
        Candidate string values.
    priority_sources:
        Ordered list of source names to prefer (highest priority first).
    source_map:
        Maps each value to its originating source name.

    Returns
    -------
    str | None
        The best value, or ``None`` if no non-empty candidates exist.
    """
    non_empty = [v for v in values if v and v.strip()]
    if not non_empty:
        return None
    # Build (priority_rank, -length, value) tuples; missing sources get rank=∞
    source_rank = {s: i for i, s in enumerate(priority_sources)}
    ranked = sorted(
        non_empty,
        key=lambda v: (
            source_rank.get(source_map.get(v, ''), len(priority_sources)),
            -len(v),
        ),
    )
    return ranked[0]


def _extract_price(drug: dict, source: str) -> DrugPrice | None:
    """Extract a single DrugPrice from a raw drug record."""
    price_data = drug.get('price') or {}
    if isinstance(price_data, dict) and price_data.get('amount') is not None:
        try:
            return DrugPrice(
                source=source,
                amount=float(price_data['amount']),
                currency=price_data.get('currency', 'BDT'),
                unit=price_data.get('unit'),
                pack_size=price_data.get('pack_size'),
            )
        except (TypeError, ValueError):
            pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Core merge logic
# ─────────────────────────────────────────────────────────────────────────────

def merge_drugs(raw_drugs: list[dict]) -> list[MergedDrug]:
    """
    Normalise, group, and merge a flat list of raw drug dicts.

    Algorithm
    ---------
    1.  Normalise each record's generic name, dosage form, and strength.
    2.  Compute a canonical id (MD5 hash) for each record.
    3.  Group records by canonical id.
    4.  For each group:
        a.  Collect all unique brand names.
        b.  Pick the most complete generic name.
        c.  Merge list fields (indications, side effects, etc.) and deduplicate.
        d.  Pick the best chemistry data (pubchem > chembl > drugbank).
        e.  Collect all BD prices.
        f.  Pick best scalar clinical/pharmacology fields.

    Parameters
    ----------
    raw_drugs:
        List of raw drug dicts (each tagged with ``_source``).

    Returns
    -------
    list[MergedDrug]
        Deduplicated, merged drug records.
    """
    now_iso = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # ── Step 1 & 2: Normalise and compute canonical ids ───────────────────
    groups: dict[str, list[dict]] = defaultdict(list)

    for drug in raw_drugs:
        generic = drug.get('generic_name') or drug.get('description') or ''
        form = drug.get('dosage_form') or ''
        strength = drug.get('strength') or ''
        cid = drug_canonical_id(generic, form, strength)
        drug['_canonical_id'] = cid
        drug['_norm_generic'] = normalize_generic_name(generic)
        drug['_norm_form'] = normalize_dosage_form(form)
        drug['_norm_strength'] = normalize_strength(strength)
        groups[cid].append(drug)

    merged_list: list[MergedDrug] = []

    # ── Step 3: Merge each group ──────────────────────────────────────────
    for cid, group in groups.items():
        sources_in_group = [d.get('_source', 'unknown') for d in group]
        unique_sources = _dedup_list(sources_in_group)

        # ── Generic name: pick the longest normalised form ────────────────
        generic_values = [d.get('generic_name') or d.get('description') or '' for d in group]
        generic_source_map = {
            d.get('generic_name') or d.get('description') or '': d.get('_source', '')
            for d in group
        }
        best_generic_raw = pick_best(
            [v for v in generic_values if v],
            PRIORITY_SOURCES,
            generic_source_map,
        )
        # Keep the raw form but normalise for the canonical field
        generic_name = normalize_generic_name(best_generic_raw) if best_generic_raw else None

        # ── Brand names ───────────────────────────────────────────────────
        brand_names = _dedup_list([
            normalize_brand_name(d.get('brand_name') or '')
            for d in group
            if d.get('brand_name')
        ])

        # ── Synonyms ──────────────────────────────────────────────────────
        synonyms: list[str] = []
        for d in group:
            synonyms.extend(_coerce_list(d.get('synonyms')))
        synonyms = _dedup_list(synonyms)

        # ── Classification ────────────────────────────────────────────────
        drug_class_map = {d.get('drug_class', ''): d.get('_source', '') for d in group}
        drug_class = pick_best(
            [d.get('drug_class') or '' for d in group],
            PRIORITY_SOURCES, drug_class_map,
        )

        tc_map = {d.get('therapeutic_class', ''): d.get('_source', '') for d in group}
        therapeutic_class = pick_best(
            [d.get('therapeutic_class') or '' for d in group],
            PRIORITY_SOURCES, tc_map,
        )

        atc_map = {d.get('atc_code', ''): d.get('_source', '') for d in group}
        atc_code = pick_best(
            [d.get('atc_code') or '' for d in group],
            PRIORITY_SOURCES, atc_map,
        )

        # ── Chemistry (pubchem > chembl > drugbank priority) ──────────────
        chem_priority = ['pubchem', 'chembl', 'drugbank', 'rxnorm'] + PRIORITY_SOURCES

        def _pick_chem(field: str) -> Any:
            vals = [d.get(field) for d in group if d.get(field) is not None]
            src_map = {str(d.get(field, '')): d.get('_source', '') for d in group}
            return pick_best([str(v) for v in vals if v is not None], chem_priority, src_map)

        mol_formula = _pick_chem('molecular_formula')
        smiles = _pick_chem('smiles')
        cas_number = _pick_chem('cas_number')

        # Numeric fields
        mol_weight_vals = [d.get('molecular_weight') for d in group if d.get('molecular_weight')]
        mol_weight: float | None = None
        for mw in mol_weight_vals:
            try:
                mol_weight = float(mw)
                break
            except (TypeError, ValueError):
                pass

        pubchem_cid: int | None = None
        for d in group:
            if d.get('pubchem_cid') is not None:
                try:
                    pubchem_cid = int(d['pubchem_cid'])
                    break
                except (TypeError, ValueError):
                    pass

        chembl_id_vals = [d.get('chembl_id') for d in group if d.get('chembl_id')]
        chembl_id = chembl_id_vals[0] if chembl_id_vals else None

        drugbank_id_vals = [d.get('drugbank_id') for d in group if d.get('drugbank_id')]
        drugbank_id = drugbank_id_vals[0] if drugbank_id_vals else None

        rxcui_vals = [d.get('rxcui') for d in group if d.get('rxcui')]
        rxcui = rxcui_vals[0] if rxcui_vals else None

        # ── Formulation ───────────────────────────────────────────────────
        dosage_form = group[0].get('_norm_form') or None
        strength = group[0].get('_norm_strength') or None

        route_map = {d.get('route', ''): d.get('_source', '') for d in group}
        route = pick_best([d.get('route') or '' for d in group], PRIORITY_SOURCES, route_map)

        # ── Manufacturers ─────────────────────────────────────────────────
        manufacturers: list[str] = []
        for d in group:
            mfr = d.get('manufacturer')
            if isinstance(mfr, dict):
                manufacturers.append(normalize_manufacturer(mfr.get('name', '')))
            elif isinstance(mfr, str):
                manufacturers.append(normalize_manufacturer(mfr))
            for mfr2 in d.get('manufacturers', []):
                if isinstance(mfr2, dict):
                    manufacturers.append(normalize_manufacturer(mfr2.get('name', '')))
                elif isinstance(mfr2, str):
                    manufacturers.append(normalize_manufacturer(mfr2))
        manufacturers = _dedup_list([m for m in manufacturers if m])

        # ── Prices ────────────────────────────────────────────────────────
        bd_prices: list[DrugPrice] = []
        for d in group:
            src = d.get('_source', '')
            if src in BD_PRICE_SOURCES:
                p = _extract_price(d, src)
                if p:
                    bd_prices.append(p)
        # Also check 'prices' list
        for d in group:
            src = d.get('_source', '')
            for price_item in d.get('prices', []):
                if isinstance(price_item, dict) and price_item.get('amount') is not None:
                    try:
                        bd_prices.append(DrugPrice(
                            source=src,
                            amount=float(price_item['amount']),
                            currency=price_item.get('currency', 'BDT'),
                            unit=price_item.get('unit'),
                            pack_size=price_item.get('pack_size'),
                        ))
                    except (TypeError, ValueError):
                        pass

        amounts = [p.amount for p in bd_prices if p.amount is not None]
        min_price = min(amounts) if amounts else None
        max_price = max(amounts) if amounts else None

        # ── Clinical list fields ──────────────────────────────────────────
        def _merge_clinical(field: str) -> list[str]:
            result: list[str] = []
            # Priority sources first
            for src in PRIORITY_SOURCES:
                for d in group:
                    if d.get('_source') == src:
                        result.extend(_coerce_list(d.get(field)))
            # Then everything else
            for d in group:
                if d.get('_source') not in PRIORITY_SOURCES:
                    result.extend(_coerce_list(d.get(field)))
            return _dedup_list(result)

        indications = _merge_clinical('indications')
        contraindications = _merge_clinical('contraindications')
        side_effects = _merge_clinical('side_effects') + _merge_clinical('adverse_reactions')
        side_effects = _dedup_list(side_effects)
        warnings = _merge_clinical('warnings') + _merge_clinical('precautions')
        warnings = _dedup_list(warnings)
        interactions = _merge_clinical('interactions')
        for d in group:
            for di in d.get('drug_interactions', []):
                if isinstance(di, dict):
                    val = di.get('name') or di.get('drug') or di.get('description')
                    if val:
                        interactions.append(str(val))
                elif isinstance(di, str):
                    interactions.append(di)
        interactions = _dedup_list(interactions)

        # ── Scalar clinical fields ────────────────────────────────────────
        def _pick_scalar(field: str, extra_priority: list[str] | None = None) -> str | None:
            priority = (extra_priority or []) + PRIORITY_SOURCES
            vals = [d.get(field) for d in group if d.get(field)]
            src_map = {str(v): d.get('_source', '') for d, v in zip(group, vals) if v}
            return pick_best([str(v) for v in vals if v], priority, src_map) or None

        dosage = _pick_scalar('dosage')
        adult_dose = _pick_scalar('adult_dose')
        pediatric_dose = _pick_scalar('pediatric_dose')
        mechanism_of_action = _pick_scalar('mechanism_of_action')

        # pharmacokinetics may be a dict or str
        pk_str: str | None = None
        for src in PRIORITY_SOURCES:
            for d in group:
                if d.get('_source') == src and d.get('pharmacokinetics'):
                    pk_val = d['pharmacokinetics']
                    if isinstance(pk_val, dict):
                        pk_str = json.dumps(pk_val)
                    else:
                        pk_str = str(pk_val)
                    break
            if pk_str:
                break

        pregnancy_category = _pick_scalar('pregnancy_category')
        lactation = _pick_scalar('lactation')

        # boxed_warning / black_box_warning
        bbw: str | None = None
        for d in group:
            bw = d.get('boxed_warning') or d.get('black_box_warning')
            if bw:
                if isinstance(bw, bool):
                    bbw = 'Yes' if bw else None
                else:
                    bbw = str(bw)
                break

        overdose = _pick_scalar('overdose')
        description = _pick_scalar('description')
        image_url = _pick_scalar('image_url')

        # ── Source URLs ───────────────────────────────────────────────────
        source_urls: dict[str, str] = {}
        for d in group:
            src = d.get('_source', 'unknown')
            url = d.get('source_url')
            if url and src not in source_urls:
                source_urls[src] = url

        merged = MergedDrug(
            id=cid,
            brand_names=brand_names,
            generic_name=generic_name,
            synonyms=synonyms,
            drug_class=drug_class or None,
            therapeutic_class=therapeutic_class or None,
            atc_code=atc_code or None,
            molecular_formula=mol_formula or None,
            molecular_weight=mol_weight,
            smiles=smiles or None,
            cas_number=cas_number or None,
            pubchem_cid=pubchem_cid,
            chembl_id=chembl_id,
            drugbank_id=drugbank_id,
            rxcui=rxcui,
            dosage_form=dosage_form or None,
            strength=strength or None,
            route=route or None,
            manufacturers=manufacturers,
            bd_prices=bd_prices,
            min_price=min_price,
            max_price=max_price,
            indications=indications,
            contraindications=contraindications,
            side_effects=side_effects,
            warnings=warnings,
            interactions=interactions,
            dosage=dosage,
            adult_dose=adult_dose,
            pediatric_dose=pediatric_dose,
            mechanism_of_action=mechanism_of_action,
            pharmacokinetics=pk_str,
            pregnancy_category=pregnancy_category,
            lactation=lactation,
            black_box_warning=bbw,
            overdose=overdose,
            description=description,
            image_url=image_url,
            sources=unique_sources,
            source_urls=source_urls,
            first_seen=now_iso,
            last_updated=now_iso,
        )
        merged_list.append(merged)

    logger.info('Merged %d raw records into %d canonical drugs', len(raw_drugs), len(merged_list))
    return merged_list
