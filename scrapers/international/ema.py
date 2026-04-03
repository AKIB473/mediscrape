"""EMA scraper - EU-authorized medicines.

EMA provides static JSON files updated twice daily at 06:00 and 18:00 CET.
No REST API - just download the full dataset as JSON.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import AsyncIterator

from models.drug import Drug, Manufacturer
from scrapers.base import BaseAPIScraper

logger = logging.getLogger(__name__)

# Static JSON data files (updated twice daily)
JSON_URLS = [
    "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines_json-report_en.json",
    "https://www.ema.europa.eu/en/documents/other/medicines-output-european-public-assessment-reports_en.json",
]


class EMAScraper(BaseAPIScraper):
    name = "ema"
    base_url = "https://www.ema.europa.eu"
    rate_limit = 1.0
    timeout = 60.0  # Large file download

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Try each JSON URL
        for json_url in JSON_URLS:
            try:
                logger.info(f"EMA: trying {json_url}")
                data = await self.api_get(json_url)

                # EMA JSON can be a list or a dict with a data key
                medicines = []
                if isinstance(data, list):
                    medicines = data
                elif isinstance(data, dict):
                    medicines = data.get("data", data.get("results", data.get("content", [])))

                if medicines:
                    logger.info(f"EMA: got {len(medicines)} medicines from JSON")
                    for med in medicines:
                        drug = self._parse_medicine(med)
                        if drug:
                            yield drug
                    return
            except Exception as e:
                logger.warning(f"EMA: JSON URL failed ({json_url}): {e}")

        # Fallback: try CSV download
        csv_urls = [
            "https://www.ema.europa.eu/sites/default/files/Medicines_output_european_public_assessment_reports.csv",
            "https://www.ema.europa.eu/en/documents/other/article-57-product-data_en.csv",
        ]
        for csv_url in csv_urls:
            try:
                logger.info(f"EMA: trying CSV {csv_url}")
                text = await self.api_get_text(csv_url)
                if text and len(text) > 100:
                    reader = csv.DictReader(io.StringIO(text))
                    count = 0
                    for row in reader:
                        drug = self._parse_csv_row(row)
                        if drug:
                            yield drug
                            count += 1
                    if count > 0:
                        logger.info(f"EMA: got {count} medicines from CSV")
                        return
            except Exception as e:
                logger.warning(f"EMA: CSV URL failed ({csv_url}): {e}")

        logger.error("EMA: all data sources failed")

    def _parse_medicine(self, med: dict) -> Drug | None:
        # Handle both camelCase and snake_case field names
        name = (
            med.get("name")
            or med.get("medicineName")
            or med.get("name_of_medicine")
            or med.get("medicine_name")
        )
        if not name:
            return None

        active = med.get("activeSubstances", med.get("activeSubstance", med.get("active_substance", [])))
        if isinstance(active, str):
            active = [active]
        generic_name = ", ".join(active) if active else None

        atc_codes = med.get("atcCodes", med.get("atcCode", med.get("atc_code_human", med.get("atc_code", []))))
        if isinstance(atc_codes, str):
            atc_codes = [atc_codes]

        therapeutic_areas = med.get("therapeuticAreas", med.get("therapeuticArea", med.get("therapeutic_area_mesh", med.get("therapeutic_area", []))))
        if isinstance(therapeutic_areas, str):
            therapeutic_areas = [therapeutic_areas]

        mah = med.get("marketingAuthorisationHolder", med.get("mah", med.get("marketing_authorisation_holder", "")))
        manufacturer = Manufacturer(name=mah) if mah else None

        url = med.get("url") or med.get("medicine_url") or "https://www.ema.europa.eu/en/medicines"

        return Drug(
            source="ema",
            source_url=url,
            source_id=med.get("productNumber", med.get("ema_product_number", med.get("id"))),
            brand_name=name,
            generic_name=generic_name,
            atc_code=atc_codes[0] if atc_codes else None,
            manufacturer=manufacturer,
            indications=therapeutic_areas,
            approval_date=med.get("authorisationDate", med.get("European_commission_decision_date", med.get("marketing_authorisation_date"))),
            categories=therapeutic_areas,
            extra={
                "product_number": med.get("productNumber", med.get("ema_product_number")),
                "authorisation_status": med.get("authorisationStatus", med.get("medicine_status")),
                "opinion_status": med.get("opinion_status"),
                "active_substances": active,
                "atc_codes": atc_codes,
                "therapeutic_areas": therapeutic_areas,
                "therapeutic_indication": med.get("therapeutic_indication"),
                "inn": med.get("inn", med.get("internationalNonproprietaryName")),
                "biosimilar": med.get("biosimilar"),
                "orphan_medicine": med.get("orphanMedicine", med.get("orphan_medicine")),
                "generic": med.get("generic"),
                "pharmaceutical_forms": med.get("pharmaceuticalForms", []),
                "species": med.get("species"),
                "category": med.get("category"),
                "decision_date": med.get("decisionDate", med.get("European_commission_decision_date")),
            },
        )

    def _parse_csv_row(self, row: dict) -> Drug | None:
        name = (
            row.get("Medicine name")
            or row.get("Product name")
            or row.get("Name")
            or ""
        ).strip()
        if not name:
            return None

        active = (
            row.get("Active substance")
            or row.get("International non-proprietary name (INN) / common name")
            or ""
        ).strip()

        mah = (
            row.get("Marketing-authorisation holder")
            or row.get("MAH")
            or ""
        ).strip()

        return Drug(
            source="ema",
            source_url=row.get("URL", "https://www.ema.europa.eu/en/medicines"),
            brand_name=name,
            generic_name=active,
            atc_code=row.get("ATC code", "").strip() or None,
            manufacturer=Manufacturer(name=mah) if mah else None,
            approval_date=row.get("Marketing-authorisation date", "").strip() or None,
            categories=[row["Therapeutic area"]] if row.get("Therapeutic area") else [],
            extra={
                k.strip(): v.strip()
                for k, v in row.items()
                if v and v.strip()
                and k.strip() not in ("Medicine name", "Product name", "Name",
                                      "Active substance", "Marketing-authorisation holder",
                                      "MAH", "ATC code", "URL")
            },
        )
