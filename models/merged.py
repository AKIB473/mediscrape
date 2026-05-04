"""Merged drug model — canonical unified record after normalisation and deduplication."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DrugPrice(BaseModel):
    """A single price observation from a BD source."""

    source: str
    amount: float | None = None
    currency: str = "BDT"
    unit: str | None = None       # e.g. "per strip", "per tablet"
    pack_size: str | None = None


class MergedDrug(BaseModel):
    """
    Canonical, deduplicated representation of a drug record assembled from one
    or more scraped sources.

    The ``id`` field is a stable MD5 hex-digest derived from the normalised
    (generic_name, dosage_form, strength) triple so the same physical drug
    always maps to the same row regardless of which scraper contributed it.
    """

    # ── Identity ─────────────────────────────────────────────────────────────
    id: str = Field(..., description="Stable MD5 canonical id: hash(generic+form+strength)")

    # ── Names ────────────────────────────────────────────────────────────────
    brand_names: list[str] = Field(default_factory=list)
    generic_name: str | None = None
    synonyms: list[str] = Field(default_factory=list)

    # ── Classification ───────────────────────────────────────────────────────
    drug_class: str | None = None
    therapeutic_class: str | None = None
    atc_code: str | None = None

    # ── Chemistry ────────────────────────────────────────────────────────────
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    smiles: str | None = None
    cas_number: str | None = None
    pubchem_cid: int | None = None
    chembl_id: str | None = None
    drugbank_id: str | None = None
    rxcui: str | None = None

    # ── Formulation ──────────────────────────────────────────────────────────
    dosage_form: str | None = None
    strength: str | None = None
    route: str | None = None

    # ── Manufacturers ────────────────────────────────────────────────────────
    manufacturers: list[str] = Field(default_factory=list)

    # ── Pricing ──────────────────────────────────────────────────────────────
    bd_prices: list[DrugPrice] = Field(default_factory=list)
    min_price: float | None = None
    max_price: float | None = None

    # ── Clinical ─────────────────────────────────────────────────────────────
    indications: list[str] = Field(default_factory=list)
    contraindications: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    interactions: list[str] = Field(default_factory=list)

    # ── Dosage ───────────────────────────────────────────────────────────────
    dosage: str | None = None
    adult_dose: str | None = None
    pediatric_dose: str | None = None

    # ── Pharmacology ─────────────────────────────────────────────────────────
    mechanism_of_action: str | None = None
    pharmacokinetics: str | None = None   # serialised as text summary

    # ── Safety ───────────────────────────────────────────────────────────────
    pregnancy_category: str | None = None
    lactation: str | None = None
    black_box_warning: str | None = None
    overdose: str | None = None
    storage: str | None = None
    boxed_warning: str | None = None

    # ── Chemical identifiers (cross-ref) ─────────────────────────────────────
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    smiles: str | None = None
    inchi: str | None = None
    inchi_key: str | None = None
    cas_number: str | None = None
    pubchem_cid: int | None = None
    chembl_id: str | None = None
    drugbank_id: str | None = None
    rxcui: str | None = None
    ndc: list[str] = Field(default_factory=list)

    # ── Extra ────────────────────────────────────────────────────────────────
    description: str | None = None
    image_url: str | None = None

    # ── Provenance ───────────────────────────────────────────────────────────
    sources: list[str] = Field(default_factory=list,
                               description="List of scraper source names that contributed")
    source_urls: dict[str, str] = Field(default_factory=dict,
                                        description="source_name -> canonical URL")
    first_seen: str | None = None   # ISO-8601 date string
    last_updated: str | None = None  # ISO-8601 date string
