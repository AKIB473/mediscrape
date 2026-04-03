"""WHO Essential Medicines List scraper - 523 essential medications."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class WHOEMLScraper(BaseScrapingScraper):
    name = "who_eml"
    base_url = "https://list.essentialmeds.org"
    rate_limit = 1.5

    async def scrape_all(self) -> AsyncIterator[Drug]:
        # WHO EML is available at list.essentialmeds.org
        # Try the API/data endpoint first
        try:
            page = await self.fetch_page(f"{self.base_url}/medicines")
            jsonld = self.extract_jsonld(page)

            # Try to find data in page scripts
            for script in page.css("script"):
                text = script.text if hasattr(script, "text") and script.text else ""
                if "medicines" in text.lower() and "{" in text:
                    try:
                        import orjson
                        # Find JSON data in script
                        start = text.index("{")
                        data = orjson.loads(text[start:])
                        items = data.get("medicines", data.get("data", []))
                        if isinstance(items, list):
                            for item in items:
                                drug = self._parse_medicine(item)
                                if drug:
                                    yield drug
                            return
                    except Exception:
                        pass
        except Exception:
            pass

        # Fallback: scrape the medicine list page
        try:
            page = await self.fetch_page(f"{self.base_url}")

            # Get all medicine links
            links = page.css('a[href*="/medicines/"], a[href*="/medicine/"]')
            urls = set()
            for link in links:
                href = link.attrib.get("href", "")
                if href:
                    full = href if href.startswith("http") else f"{self.base_url}{href}"
                    urls.add(full)

            logger.info(f"WHO EML: found {len(urls)} medicine URLs")

            for url in urls:
                try:
                    drug = await self._scrape_medicine_page(url)
                    if drug:
                        yield drug
                except Exception as e:
                    logger.warning(f"WHO EML: error scraping {url}: {e}")
        except Exception as e:
            logger.error(f"WHO EML: failed to load main page: {e}")

        # Also try the WHO main site
        try:
            page = await self.fetch_page("https://www.who.int/groups/expert-committee-on-selection-and-use-of-essential-medicines/essential-medicines-lists")
            for link in page.css('a[href*="essential"]'):
                href = link.attrib.get("href", "")
                logger.debug(f"WHO link: {href}")
        except Exception:
            pass

    def _parse_medicine(self, item: dict) -> Drug | None:
        name = item.get("name") or item.get("title") or item.get("inn")
        if not name:
            return None

        return Drug(
            source="who_eml",
            source_url=f"{self.base_url}/medicines/{item.get('id', '')}",
            source_id=str(item.get("id", "")),
            generic_name=name,
            dosage_form=item.get("dosage_form") or item.get("form"),
            strength=item.get("strength") or item.get("dose"),
            route=item.get("route"),
            therapeutic_class=item.get("section") or item.get("category"),
            categories=[item["section"]] if item.get("section") else [],
            extra={
                "eml_section": item.get("section"),
                "eml_subsection": item.get("subsection"),
                "complementary": item.get("complementary", False),
                "age_group": item.get("age_group"),
                "formulation_type": item.get("formulation_type"),
                "notes": item.get("notes"),
                "square_box": item.get("square_box"),  # Therapeutic equivalence marker
                "who_list_number": item.get("list_number"),
            },
        )

    async def _scrape_medicine_page(self, url: str) -> Drug | None:
        # Primary path: use the structured JSON-LD endpoint available per medicine.
        jsonld_data = await self._fetch_medicine_jsonld(url)
        if jsonld_data:
            parsed = self._parse_medicine_jsonld(jsonld_data, url)
            if parsed:
                return parsed

        # Fallback path: parse HTML detail page.
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        title = _text(page.css_first("h1, .medicine-name"))
        if not title:
            return None

        fields = {}
        for row in page.css("tr, .detail-item, dt"):
            label = _text(row.css_first("th, .label, dt"))
            value = _text(row.css_first("td, .value, dd"))
            if label and value:
                fields[label.lower().strip().rstrip(":")] = value

        return Drug(
            source="who_eml",
            source_url=url,
            generic_name=title,
            dosage_form=fields.get("dosage form", fields.get("form", "")),
            strength=fields.get("strength", ""),
            route=fields.get("route", ""),
            therapeutic_class=fields.get("section", fields.get("category", "")),
            extra={
                "jsonld": jsonld,
                "all_fields": fields,
                "who_essential": True,
            },
        )

    async def _fetch_medicine_jsonld(self, url: str) -> dict | None:
        try:
            import orjson

            jsonld_url = url if url.endswith(".jsonld") else f"{url.rstrip('/')}.jsonld"
            response = await self.fetch_page(jsonld_url)
            payload = b""
            if hasattr(response, "body") and response.body:
                payload = response.body if isinstance(response.body, bytes) else str(response.body).encode("utf-8")
            elif hasattr(response, "text") and response.text:
                payload = response.text.encode("utf-8")
            if not payload:
                return None
            data = orjson.loads(payload)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _parse_medicine_jsonld(self, data: dict, source_url: str) -> Drug | None:
        name = data.get("name") or data.get("nonProprietaryName")
        if not name:
            return None

        active_ingredients = _as_list(data.get("activeIngredient"))
        ingredient_names = []
        for ingredient in _as_list(data.get("ingredient")):
            if isinstance(ingredient, dict) and ingredient.get("name"):
                ingredient_names.append(str(ingredient["name"]))

        generic_name = (
            data.get("nonProprietaryName")
            or _first(active_ingredients)
            or _first(ingredient_names)
            or name
        )
        description = _strip_html(str(data.get("description", "")))

        identifier = str(data.get("@id", "") or "").strip()
        source_id = None
        if identifier:
            match = re.search(r"/medicines/(\d+)", identifier)
            source_id = match.group(1) if match else identifier

        return Drug(
            source="who_eml",
            source_url=source_url,
            source_id=source_id,
            generic_name=generic_name,
            brand_name=name if name != generic_name else None,
            therapeutic_class=data.get("therapeuticArea") or data.get("category"),
            description=description or None,
            monograph_url=data.get("sameAs"),
            categories=[c for c in [data.get("therapeuticArea"), data.get("category")] if c],
            extra={
                "who_essential": True,
                "status": data.get("status"),
                "drug_unit": _as_list(data.get("drugUnit")),
                "guideline_refs": [
                    item.get("@id")
                    for item in _as_list(data.get("guideline"))
                    if isinstance(item, dict) and item.get("@id")
                ],
                "equivalent_for": _as_list(data.get("equivalentFor")),
                "antibiotic_stewardship_group": _as_list(data.get("antibioticStewardshipGroup")),
                "active_ingredients": active_ingredients,
                "ingredient_names": ingredient_names,
                "jsonld": data,
            },
        )


def _text(elem) -> str:
    if elem is None:
        return ""
    return elem.text.strip() if hasattr(elem, "text") and elem.text else ""


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first(items: list[str]) -> str | None:
    return items[0] if items else None


def _strip_html(text: str) -> str:
    if not text:
        return ""
    no_tags = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", no_tags).strip()
