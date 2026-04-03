"""Epocrates scraper.

Hybrid strategy:
- API catalog endpoints from `/drugs-web-app/api/v1/*`
- Card/details endpoints from `/online/v2/card/drug`
- Optional monograph HTML section extraction
"""

from __future__ import annotations

import logging
import os
import re
from typing import AsyncIterator

import orjson

from models.drug import Drug
from scrapers.base import BaseAPIScraper

logger = logging.getLogger(__name__)

CATALOG_URL = "https://www.epocrates.com/drugs-web-app/api/v1/drugs"
PARENT_CLASS_URL = "https://www.epocrates.com/drugs-web-app/api/v1/drugClassification"
BRANDS_URL = "https://www.epocrates.com/drugs-web-app/api/v1/drugBrands"
CARD_URL = "https://www.epocrates.com/online/v2/card/drug"
HOME_URL = "https://www.epocrates.com/online/drugs"


class EpocratesScraper(BaseAPIScraper):
    name = "epocrates"
    base_url = "https://www.epocrates.com"
    rate_limit = 0.15
    timeout = 45.0
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.epocrates.com/online/drugs",
        "User-Agent": "Mozilla/5.0",
    }

    def __init__(self, data_dir):
        super().__init__(data_dir=data_dir)
        self.max_drugs = _to_int(os.getenv("EPOCRATES_MAX_DRUGS"), 0)
        # Full monograph pages are expensive. Enabled by default to maximize field union.
        self.fetch_monograph = os.getenv("EPOCRATES_FETCH_MONOGRAPH", "1").lower() not in {"0", "false", "no"}

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # Prime cookies/session for endpoints that expect browser-ish flow.
        await self._safe_get_text(HOME_URL)

        parent_classes = await self._fetch_parent_classes()
        class_map = await self._build_parent_class_map(parent_classes)

        catalog = await self.api_get(CATALOG_URL)
        items = catalog.get("data", {}).get("drugs", [])
        logger.info(f"Epocrates: catalog returned {len(items)} drugs")

        emitted = 0
        for item in items:
            if self.max_drugs and emitted >= self.max_drugs:
                break

            drug_id = item.get("id")
            if drug_id is None:
                continue

            try:
                card = await self._safe_get_json(CARD_URL, params={"drugId": drug_id})
            except Exception as e:
                logger.warning(f"Epocrates: card fetch failed for {drug_id}: {e}")
                card = {}

            brands = await self._safe_get_json_list(
                BRANDS_URL,
                params={"drugId": drug_id, "includeParent": "true"},
            )

            monograph_link = card.get("monographLink")
            sections = {}
            monograph_html = ""
            if self.fetch_monograph and monograph_link:
                monograph_url = _to_absolute(monograph_link, self.base_url)
                monograph_html = await self._safe_get_text(monograph_url)
                if monograph_html:
                    sections = _extract_sections_from_h2(monograph_html)

            drug = self._build_drug(item=item, card=card, sections=sections, brands=brands)
            if not drug:
                continue
            emitted += 1

            if class_map.get(str(drug_id)):
                drug.categories = sorted(class_map[str(drug_id)])

            # Union-style source payload retention
            drug.extra["catalog_item"] = item
            drug.extra["card"] = card
            drug.extra["brands"] = brands
            if monograph_html:
                drug.extra["monograph_html_sample"] = monograph_html[:2000]
            drug.extra["sections"] = sections
            drug.extra["parent_classes"] = sorted(class_map.get(str(drug_id), set()))

            yield drug

    async def _fetch_parent_classes(self) -> list[dict]:
        try:
            data = await self.api_get(PARENT_CLASS_URL, params={"isParentClass": "true"})
            return data.get("data", {}).get("parentDrugClass", [])
        except Exception as e:
            logger.warning(f"Epocrates: failed to fetch parent classes: {e}")
            return []

    async def _build_parent_class_map(self, parent_classes: list[dict]) -> dict[str, set[str]]:
        mapping: dict[str, set[str]] = {}

        for cls in parent_classes:
            class_id = cls.get("id")
            class_name = str(cls.get("name", "")).strip()
            if class_id is None or not class_name:
                continue
            try:
                data = await self.api_get(CATALOG_URL, params={"parentClassId": class_id})
            except Exception as e:
                logger.warning(f"Epocrates: class mapping failed for {class_name} ({class_id}): {e}")
                continue

            for item in data.get("data", {}).get("drugs", []):
                drug_id = item.get("id")
                if drug_id is None:
                    continue
                key = str(drug_id)
                mapping.setdefault(key, set()).add(class_name)

        return mapping

    def _build_drug(self, item: dict, card: dict, sections: dict[str, str], brands: list[dict]) -> Drug | None:
        drug_id = item.get("id")
        if drug_id is None:
            return None

        discovered_brand_names = [
            str(b.get("name") or "").strip()
            for b in brands
            if isinstance(b, dict) and str(b.get("name") or "").strip()
        ]
        brand_name = _first_non_empty(
            [
                str(item.get("name") or ""),
                str(card.get("drugName") or ""),
                _first_non_empty(discovered_brand_names),
            ]
        )
        generic_name = _first_non_empty(
            [
                _clean_generic(str(item.get("generic", {}).get("name", ""))),
                _clean_generic(str(card.get("genericName", ""))),
            ]
        )
        if generic_name and brand_name and generic_name.lower() == brand_name.lower():
            brand_name = None
        synonyms = _dedupe_preserve_order(
            [
                name
                for name in discovered_brand_names
                if name.lower() not in {str(brand_name or "").lower(), str(generic_name or "").lower()}
            ]
        )

        monograph_link = str(card.get("monographLink") or "").strip()
        monograph_url = _to_absolute(monograph_link, self.base_url) if monograph_link else None

        schedule = str(card.get("deaFdaStatusCode") or "").strip() or None

        indications = _split_text(_find_section(sections, ["indications", "uses"]))
        contraindications = _split_text(
            _find_section(sections, ["contraindications", "contraindications/cautions", "cautions"])
        )
        side_effects = _split_text(_find_section(sections, ["adverse reactions", "adverse effects", "side effects"]))
        adult_dose = _find_section(sections, ["adult dosing", "adult dose"])
        pediatric_dose = _find_section(sections, ["peds dosing", "pediatric dosing"])
        dosage = adult_dose or _find_section(sections, ["dosing", "dosage"])

        sub_sections = card.get("subSections", []) or []
        interaction_links = [
            s.get("link")
            for s in sub_sections
            if isinstance(s, dict) and "interact" in str(s.get("name", "")).lower()
        ]

        return Drug(
            source="epocrates",
            source_url=monograph_url or f"{self.base_url}/online/drugs/{drug_id}",
            source_id=str(drug_id),
            brand_name=brand_name,
            generic_name=generic_name,
            synonyms=synonyms,
            schedule=schedule,
            indications=indications,
            contraindications=contraindications,
            side_effects=side_effects,
            interactions=_split_text(_find_section(sections, ["interactions"])) + _clean_links(interaction_links),
            dosage=dosage,
            adult_dose=adult_dose,
            pediatric_dose=pediatric_dose,
            black_box_warning=bool(card.get("bbwSectionLink")),
            description=_find_section(sections, ["overview", "summary"]) or None,
            monograph_url=monograph_url,
            extra={
                "dea_fda_status_code": card.get("deaFdaStatusCode"),
                "dea_fda_status_desc": card.get("deaFdaStatusDesc"),
                "generic_id": card.get("genericId"),
                "generic_drug_link": card.get("genericDrugLink"),
                "multi_brand": card.get("multiBrand"),
                "sub_sections": sub_sections,
                "bbw_section_link": card.get("bbwSectionLink"),
                "brand_ids": [
                    b.get("id")
                    for b in brands
                    if isinstance(b, dict) and b.get("id") is not None
                ],
                "brand_names": discovered_brand_names,
                "drug_type_id": (item.get("drugType") or {}).get("id"),
                "drug_name_raw": item.get("name"),
                "generic_raw": item.get("generic"),
            },
        )

    async def _safe_get_text(self, url: str) -> str:
        try:
            return await self.api_get_text(url)
        except Exception as e:
            logger.warning(f"Epocrates: text fetch failed {url}: {e}")
            return ""

    async def _safe_get_json(self, url: str, params: dict | None = None) -> dict:
        parsed = await self._safe_get_json_any(url, params=params)
        return parsed if isinstance(parsed, dict) else {}

    async def _safe_get_json_list(self, url: str, params: dict | None = None) -> list[dict]:
        parsed = await self._safe_get_json_any(url, params=params)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        return []

    async def _safe_get_json_any(self, url: str, params: dict | None = None):
        try:
            payload = await self.api_get_text(url, params=params)
        except Exception as e:
            logger.warning(f"Epocrates: json fetch failed {url}: {e}")
            return {}

        text = payload.strip()
        if not text:
            return {}

        try:
            return orjson.loads(text)
        except Exception:
            return {}


def _to_absolute(path: str, base_url: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("/"):
        return f"{base_url}{path}"
    return f"{base_url}/{path}"


def _extract_sections_from_h2(html: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    if not html:
        return sections

    # Remove script/style blocks so section text doesn't include JS/CSS payload.
    html = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    html = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", html)

    parts = re.split(r"(?is)<h2[^>]*>(.*?)</h2>", html)
    for i in range(1, len(parts), 2):
        heading = _clean_text(parts[i]).lower()
        content_html = parts[i + 1] if i + 1 < len(parts) else ""
        content = _clean_text(content_html)
        if heading and content:
            sections[heading] = content[:12000]
    return sections


def _clean_text(text: str) -> str:
    if not text:
        return ""
    txt = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", txt).strip()


def _split_text(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?:•|\n|;|\.\s{1,})", text)
    return [p.strip() for p in parts if p and p.strip()]


def _find_section(sections: dict[str, str], names: list[str]) -> str:
    for wanted in names:
        wanted_l = wanted.lower()
        for key, value in sections.items():
            if wanted_l in key:
                return value
    return ""


def _first_non_empty(values: list[str]) -> str | None:
    for value in values:
        txt = str(value or "").strip()
        if txt:
            return txt
    return None


def _clean_generic(name: str) -> str:
    txt = (name or "").strip()
    if txt.lower() == "view brands":
        return ""
    return txt


def _clean_links(links: list[str]) -> list[str]:
    cleaned = []
    for link in links:
        txt = str(link or "").strip()
        if txt:
            cleaned.append(txt)
    return cleaned


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        key = str(item or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(str(item).strip())
    return ordered


def _to_int(raw: str | None, default: int) -> int:
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default
