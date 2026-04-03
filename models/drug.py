from __future__ import annotations

import orjson
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class Manufacturer(BaseModel):
    name: str
    country: str | None = None
    website: str | None = None


class DrugPrice(BaseModel):
    amount: float | None = None
    currency: str = "BDT"
    unit: str | None = None  # e.g., "per strip", "per tablet"
    pack_size: str | None = None


class Drug(BaseModel):
    # Identity
    source: str  # Which scraper produced this
    source_url: str
    source_id: str | None = None

    # Basic info
    brand_name: str | None = None
    generic_name: str | None = None
    synonyms: list[str] = Field(default_factory=list)

    # Classification
    drug_class: str | None = None
    therapeutic_class: str | None = None
    pharmacological_class: str | None = None
    atc_code: str | None = None
    schedule: str | None = None
    otc: bool | None = None

    # Chemistry
    chemical_name: str | None = None
    molecular_formula: str | None = None
    molecular_weight: float | None = None
    cas_number: str | None = None
    inchi: str | None = None
    inchi_key: str | None = None
    smiles: str | None = None
    pubchem_cid: int | None = None
    chembl_id: str | None = None
    drugbank_id: str | None = None
    rxcui: str | None = None
    ndc: list[str] = Field(default_factory=list)
    unii: str | None = None

    # Formulation
    dosage_form: str | None = None
    strength: str | None = None
    route: str | None = None
    formulations: list[dict] = Field(default_factory=list)

    # Manufacturer
    manufacturer: Manufacturer | None = None
    manufacturers: list[Manufacturer] = Field(default_factory=list)

    # Pricing
    price: DrugPrice | None = None
    prices: list[DrugPrice] = Field(default_factory=list)

    # Clinical
    indications: list[str] = Field(default_factory=list)
    contraindications: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    adverse_reactions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    precautions: list[str] = Field(default_factory=list)
    interactions: list[str] = Field(default_factory=list)
    drug_interactions: list[dict] = Field(default_factory=list)
    food_interactions: list[str] = Field(default_factory=list)

    # Dosage
    dosage: str | None = None
    adult_dose: str | None = None
    pediatric_dose: str | None = None
    geriatric_dose: str | None = None
    renal_dose: str | None = None
    hepatic_dose: str | None = None
    max_dose: str | None = None

    # Pharmacology
    mechanism_of_action: str | None = None
    pharmacodynamics: str | None = None
    pharmacokinetics: dict | None = None
    absorption: str | None = None
    distribution: str | None = None
    metabolism: str | None = None
    elimination: str | None = None
    half_life: str | None = None
    bioavailability: str | None = None
    protein_binding: str | None = None
    volume_of_distribution: str | None = None
    clearance: str | None = None

    # Safety
    pregnancy_category: str | None = None
    lactation: str | None = None
    boxed_warning: str | None = None
    black_box_warning: bool | None = None
    rems: bool | None = None
    overdose: str | None = None

    # Regulatory
    approval_date: str | None = None
    market_date: str | None = None
    withdrawal_date: str | None = None
    patent_expiry: str | None = None
    exclusivity: str | None = None
    registration_number: str | None = None
    approved_countries: list[str] = Field(default_factory=list)

    # Storage
    storage: str | None = None
    shelf_life: str | None = None

    # Additional
    description: str | None = None
    monograph_url: str | None = None
    label_url: str | None = None
    image_url: str | None = None
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # Extras - catch-all for source-specific fields
    extra: dict = Field(default_factory=dict)

    def to_json_bytes(self) -> bytes:
        return orjson.dumps(
            self.model_dump(exclude_none=True, exclude_defaults=True),
            option=orjson.OPT_INDENT_2,
        )


class ScrapeMeta(BaseModel):
    source: str
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_drugs: int = 0
    new_drugs: int = 0
    updated_drugs: int = 0
    errors: int = 0
    duration_seconds: float = 0
    checksum: str | None = None
