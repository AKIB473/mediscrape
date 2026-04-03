"""DGHS SHR scraper.

Sources:
- Published Bangladesh Core FHIR artifacts (public)
- Optional live FHIR Medication endpoint (institutional auth required)
"""

from __future__ import annotations

import logging
import os
import re
from typing import AsyncIterator

from models.drug import Drug
from scrapers.base import BaseAPIScraper

logger = logging.getLogger(__name__)


class DGHSSHRScraper(BaseAPIScraper):
    name = "dghs_shr"
    base_url = "https://fhir.dghs.gov.bd"
    rate_limit = 0.25
    timeout = 45.0
    headers = {
        "Accept": "application/fhir+json, application/json",
        "User-Agent": "MediScrape/1.0 (+https://fhir.dghs.gov.bd)",
    }

    def __init__(self, data_dir):
        super().__init__(data_dir=data_dir)
        self.core_base = os.getenv("DGHS_SHR_CORE_BASE", "https://fhir.dghs.gov.bd/core").rstrip("/")
        self.fhir_base = os.getenv("DGHS_SHR_FHIR_BASE", "https://fhir.dghs.gov.bd/fhir").rstrip("/")
        self.max_live_medications = _to_int(os.getenv("DGHS_SHR_MAX_MEDICATIONS"), 0)
        token = os.getenv("DGHS_SHR_BEARER_TOKEN")
        if token:
            self.client.headers["Authorization"] = f"Bearer {token}"
        self._has_live_token = bool(token)

    async def scrape_all(self) -> AsyncIterator[Drug]:
        code_system = await self._safe_api_get(f"{self.core_base}/CodeSystem-bd-medication-code.json")
        value_set = await self._safe_api_get(f"{self.core_base}/ValueSet-bd-medication-valueset.json")
        med_profile = await self._safe_api_get(f"{self.core_base}/StructureDefinition-bd-medication.json")
        med_request_profile = await self._safe_api_get(f"{self.core_base}/StructureDefinition-bd-medication-request.json")

        seen_ids: set[str] = set()
        for concept in (code_system or {}).get("concept", []):
            drug = self._parse_codesystem_concept(
                concept=concept,
                code_system=code_system or {},
                value_set=value_set or {},
                med_profile=med_profile or {},
                med_request_profile=med_request_profile or {},
            )
            if not drug:
                continue
            source_id = drug.source_id or ""
            if source_id and source_id in seen_ids:
                continue
            if source_id:
                seen_ids.add(source_id)
            yield drug

        if not self._has_live_token:
            logger.info(
                "DGHS SHR live FHIR Medication feed requires DGHS_SHR_BEARER_TOKEN; "
                "using public core terminology artifacts only."
            )
            return

        emitted_live = 0
        async for drug in self._scrape_live_medications():
            source_id = drug.source_id or ""
            if source_id and source_id in seen_ids:
                continue
            if source_id:
                seen_ids.add(source_id)
            yield drug
            emitted_live += 1
            if self.max_live_medications and emitted_live >= self.max_live_medications:
                break

    async def _scrape_live_medications(self) -> AsyncIterator[Drug]:
        next_url = f"{self.fhir_base}/Medication"
        params: dict | None = {"_count": 100, "_format": "json"}
        page = 0

        while next_url:
            page += 1
            bundle = await self._safe_api_get(next_url, params=params)
            if not bundle:
                break

            entries = bundle.get("entry", [])
            for entry in entries:
                resource = entry.get("resource", {}) if isinstance(entry, dict) else {}
                if resource.get("resourceType") != "Medication":
                    continue
                drug = self._parse_fhir_medication(resource)
                if drug:
                    yield drug

            next_url = self._bundle_next_url(bundle)
            params = None  # next link is fully qualified
            if not next_url:
                break

    def _parse_codesystem_concept(
        self,
        concept: dict,
        code_system: dict,
        value_set: dict,
        med_profile: dict,
        med_request_profile: dict,
    ) -> Drug | None:
        code = str(concept.get("code", "")).strip()
        display = str(concept.get("display", "")).strip()
        definition = str(concept.get("definition", "")).strip()
        if not code and not display and not definition:
            return None

        generic_name = definition or display or None
        brand_name = display if display and definition and display != definition else None

        return Drug(
            source="dghs_shr",
            source_url=f"{self.core_base}/CodeSystem-bd-medication-code.json",
            source_id=code or None,
            brand_name=brand_name,
            generic_name=generic_name,
            description=definition or None,
            categories=["Bangladesh Core FHIR", "Medication"],
            extra={
                "dataset": "bd-core-terminology",
                "code_system_url": code_system.get("url"),
                "code_system_version": code_system.get("version"),
                "code_system_status": code_system.get("status"),
                "code_system_title": code_system.get("title"),
                "code_system_count": code_system.get("count"),
                "value_set_url": value_set.get("url"),
                "value_set_version": value_set.get("version"),
                "value_set_status": value_set.get("status"),
                "medication_profile_url": med_profile.get("url"),
                "medication_request_profile_url": med_request_profile.get("url"),
                "concept": concept,
            },
        )

    def _parse_fhir_medication(self, resource: dict) -> Drug | None:
        code_block = resource.get("code", {}) or {}
        coding = (code_block.get("coding") or [{}])[0]
        code = str(coding.get("code") or "").strip()
        display = str(coding.get("display") or "").strip()
        name_text = str(code_block.get("text") or "").strip()

        identifiers = resource.get("identifier", []) or []
        identifier_value = None
        if identifiers and isinstance(identifiers[0], dict):
            identifier_value = identifiers[0].get("value")

        ingredients = []
        for ing in resource.get("ingredient", []) or []:
            if not isinstance(ing, dict):
                continue
            item = ing.get("itemCodeableConcept", {}) or {}
            if item.get("text"):
                ingredients.append(str(item["text"]))
                continue
            for c in item.get("coding", []) or []:
                if isinstance(c, dict) and c.get("display"):
                    ingredients.append(str(c["display"]))

        form = resource.get("form", {}) or {}
        dosage_form = str(form.get("text") or "").strip() or _first_display(form.get("coding", []))
        status = str(resource.get("status") or "").strip() or None

        generic_name = _first_non_empty([_first(ingredients), display, name_text, str(identifier_value or "")])
        brand_name = _first_non_empty([name_text, display])
        if brand_name and generic_name and brand_name == generic_name:
            brand_name = None

        source_id = _first_non_empty([str(identifier_value or ""), code, str(resource.get("id") or "")])
        if not source_id and not generic_name and not brand_name:
            return None

        warnings = []
        for ext in resource.get("extension", []) or []:
            if isinstance(ext, dict) and ext.get("valueString"):
                warnings.append(str(ext["valueString"]))

        return Drug(
            source="dghs_shr",
            source_url=f"{self.fhir_base}/Medication",
            source_id=source_id,
            brand_name=brand_name,
            generic_name=generic_name,
            dosage_form=dosage_form or None,
            warnings=warnings,
            categories=["Bangladesh SHR", "FHIR Medication"],
            extra={
                "dataset": "dghs-shr-live-fhir",
                "fhir_resource_id": resource.get("id"),
                "fhir_status": status,
                "fhir_meta": resource.get("meta"),
                "fhir_identifier": identifiers,
                "fhir_code": code_block,
                "fhir_ingredients": resource.get("ingredient", []),
                "fhir_batch": resource.get("batch"),
                "fhir_extension": resource.get("extension", []),
                "raw_resource": resource,
            },
        )

    @staticmethod
    def _bundle_next_url(bundle: dict) -> str | None:
        for link in bundle.get("link", []) or []:
            if isinstance(link, dict) and link.get("relation") == "next":
                return link.get("url")
        return None

    async def _safe_api_get(self, url: str, params: dict | None = None) -> dict | None:
        try:
            return await self.api_get(url, params=params)
        except Exception as e:
            logger.warning(f"DGHS SHR: failed GET {url}: {e}")
            return None


def _first(items: list[str]) -> str | None:
    return items[0] if items else None


def _first_non_empty(values: list[str]) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def _first_display(codings: list[dict]) -> str | None:
    for c in codings or []:
        if isinstance(c, dict) and c.get("display"):
            return str(c["display"])
    return None


def _to_int(raw: str | None, default: int) -> int:
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
