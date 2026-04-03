"""Medscape drug reference scraper.

Uses category pages + drug monographs with JSON-LD and section extraction.
"""

from __future__ import annotations

import logging
import os
import re
import html as html_lib
from typing import AsyncIterator

import orjson

from models.drug import Drug
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class MedscapeScraper(BaseScrapingScraper):
    name = "medscape"
    base_url = "https://reference.medscape.com"
    rate_limit = 0.75

    def __init__(self, data_dir):
        super().__init__(data_dir=data_dir)
        self.max_drugs = _to_int(os.getenv("MEDSCAPE_MAX_DRUGS"), 0)

    async def scrape_all(self) -> AsyncIterator[Drug]:
        category_urls = await self._get_category_urls()
        logger.info(f"Medscape: found {len(category_urls)} categories")

        drug_urls: set[str] = set()
        for category_url in category_urls:
            if self.max_drugs and len(drug_urls) >= self.max_drugs:
                break
            try:
                links = await self._extract_drug_urls_from_category(category_url)
                drug_urls.update(links)
            except Exception as e:
                logger.warning(f"Medscape: category scrape failed {category_url}: {e}")

        sorted_urls = sorted(drug_urls)
        logger.info(f"Medscape: found {len(sorted_urls)} unique drug URLs")

        emitted = 0
        for url in sorted_urls:
            if self.max_drugs and emitted >= self.max_drugs:
                break
            try:
                drug = await self._scrape_drug_page(url)
                if not drug:
                    continue
                emitted += 1
                yield drug
            except Exception as e:
                logger.warning(f"Medscape: failed {url}: {e}")

    async def _get_category_urls(self) -> list[str]:
        page = await self.fetch_page(f"{self.base_url}/drugs")
        categories: set[str] = set()

        for link in page.css('a[href*="/drugs/"]'):
            href = link.attrib.get("href", "")
            if not href:
                continue
            full = _to_absolute(href, self.base_url)
            if not full.startswith(f"{self.base_url}/drugs/"):
                continue
            if "/features/" in full:
                continue
            # Keep canonical category URL only.
            m = re.match(rf"^{re.escape(self.base_url)}/drugs/([a-z0-9-]+)", full)
            if not m:
                continue
            categories.add(f"{self.base_url}/drugs/{m.group(1)}")

        return sorted(categories)

    async def _extract_drug_urls_from_category(self, category_url: str) -> set[str]:
        urls: set[str] = set()
        queue = [category_url]
        visited: set[str] = set()

        while queue:
            page_url = queue.pop(0)
            if page_url in visited:
                continue
            visited.add(page_url)

            page = await self.fetch_page(page_url)

            for link in page.css('a[href*="/drug/"]'):
                href = link.attrib.get("href", "")
                if not href:
                    continue
                full = _to_absolute(href, self.base_url)
                if re.search(r"/drug/[a-z0-9-]+-\d+$", full):
                    urls.add(full)

            # Pagination-aware crawl: if a category exposes page links,
            # enqueue additional pages discovered via query params.
            for link in page.css('a[href*="?page="], a[rel="next"], a[aria-label*="Next"]'):
                href = link.attrib.get("href", "")
                if not href:
                    continue
                full = _to_absolute(href, self.base_url)
                if not full.startswith(category_url):
                    continue
                if full not in visited:
                    queue.append(full)

        return urls

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        raw_html = _response_html(page)
        jsonld_blocks = self.extract_jsonld(page)
        if not jsonld_blocks:
            jsonld_blocks = _extract_jsonld_from_html(raw_html)

        title_text = _first_non_empty(
            [
                _extract_h1_text(raw_html),
                _clean_text(_text(page.css_first("h1"))),
                _extract_title_text(raw_html),
                _slug_name_from_url(url),
            ]
        )
        drug_jsonld = _find_drug_jsonld(jsonld_blocks)
        sections = _extract_sections_from_h2(raw_html)
        drug_class_values = _drug_class_names((drug_jsonld or {}).get("drugClass"))

        generic_name = _normalize_generic(
            _first_non_empty(
            [
                _clean_text(str((drug_jsonld or {}).get("nonProprietaryName", ""))),
                sections.get("generic name"),
                title_text,
            ]
            )
        )
        brand_name = _first_non_empty(
            [
                _clean_text(str((drug_jsonld or {}).get("name", ""))),
                title_text,
            ]
        )
        if generic_name and brand_name and generic_name.lower() == brand_name.lower():
            brand_name = None

        if not generic_name and not brand_name:
            return None

        interactions = _jsonld_interactions(drug_jsonld or {})
        warnings = _as_list((drug_jsonld or {}).get("warning"))
        drug_class = _first_non_empty(drug_class_values)
        image_url = _first_non_empty(_as_list((drug_jsonld or {}).get("image")))

        return Drug(
            source="medscape",
            source_url=url,
            source_id=_source_id_from_url(url),
            brand_name=brand_name,
            generic_name=generic_name,
            drug_class=drug_class,
            indications=_split_sections(sections, ["indications", "uses"]),
            contraindications=_split_sections(sections, ["contraindications", "contraindications/cautions"]),
            side_effects=_split_sections(sections, ["adverse effects", "adverse reactions"]),
            warnings=warnings or _split_sections(sections, ["warnings"]),
            interactions=interactions or _split_sections(sections, ["interactions"]),
            dosage=sections.get("dosing & uses") or sections.get("dosing and uses"),
            adult_dose=sections.get("adult dosing"),
            pediatric_dose=sections.get("peds dosing") or sections.get("pediatric dosing"),
            pregnancy_category=_first_non_empty(_split_sections(sections, ["pregnancy & lactation", "pregnancy"])),
            mechanism_of_action=sections.get("pharmacology"),
            description=_first_non_empty(
                [
                    _clean_text(str((drug_jsonld or {}).get("description", ""))),
                    sections.get("overview"),
                    sections.get("dosing & uses"),
                ]
            ),
            image_url=image_url,
            categories=drug_class_values,
            extra={
                "jsonld": jsonld_blocks,
                "drug_jsonld": drug_jsonld,
                "sections": sections,
                "prescription_status": (drug_jsonld or {}).get("prescriptionStatus"),
                "interacting_drugs_jsonld": (drug_jsonld or {}).get("interactingDrug"),
                "raw_url_slug": _slug_from_url(url),
            },
        )


def _to_absolute(href: str, base_url: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("/"):
        return f"{base_url}{href}"
    return f"{base_url}/{href}"


def _response_html(page) -> str:
    body = getattr(page, "body", None)
    if isinstance(body, bytes) and body:
        return body.decode("utf-8", errors="ignore")
    text = getattr(page, "text", None)
    if isinstance(text, str):
        return text
    return ""


def _text(elem) -> str:
    if elem is None:
        return ""
    text = elem.text if hasattr(elem, "text") else ""
    return str(text or "").strip()


def _clean_text(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\(Rx\)|\(OTC\)", "", text, flags=re.I)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html_lib.unescape(cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_sections_from_h2(html: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    if not html:
        return sections

    parts = re.split(r"(?is)<h2[^>]*>(.*?)</h2>", html)
    # parts layout: [prelude, heading1, content1, heading2, content2, ...]
    for i in range(1, len(parts), 2):
        heading_raw = parts[i]
        content_raw = parts[i + 1] if i + 1 < len(parts) else ""
        heading = _clean_text(heading_raw).lower()
        content = _clean_text(content_raw)
        if not heading or not content:
            continue
        # keep section content bounded to avoid huge blobs
        sections[heading] = content[:12000]

    return sections


def _extract_h1_text(html: str) -> str:
    if not html:
        return ""
    match = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", html)
    if not match:
        return ""
    return _clean_text(match.group(1))


def _extract_title_text(html: str) -> str:
    if not html:
        return ""
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if not match:
        return ""
    title = _clean_text(match.group(1))
    # Medscape titles are commonly like "<drug>: ... - Medscape"
    title = re.sub(r"\s*-\s*medscape.*$", "", title, flags=re.I).strip()
    if ":" in title:
        title = title.split(":", 1)[0].strip()
    return title


def _extract_jsonld_from_html(html: str) -> list[dict]:
    if not html:
        return []
    blocks: list[dict] = []
    scripts = re.findall(r'(?is)<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html)
    for raw in scripts:
        txt = raw.strip()
        if not txt:
            continue
        txt = html_lib.unescape(txt)
        try:
            parsed = orjson.loads(txt)
        except Exception:
            continue
        if isinstance(parsed, list):
            blocks.extend([item for item in parsed if isinstance(item, dict)])
        elif isinstance(parsed, dict):
            blocks.append(parsed)
    return blocks


def _find_drug_jsonld(blocks: list[dict]) -> dict | None:
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("@type")
        if block_type == "Drug":
            return block
        if isinstance(block_type, list) and "Drug" in block_type:
            return block
    return None


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return [text] if text else []


def _jsonld_interactions(drug_jsonld: dict) -> list[str]:
    items = drug_jsonld.get("interactingDrug")
    if not items:
        return []
    if not isinstance(items, list):
        items = [items]

    interactions: list[str] = []
    for item in items:
        if isinstance(item, str):
            interactions.append(item.strip())
        elif isinstance(item, dict):
            text = str(item.get("name") or item.get("drugName") or item.get("@id") or "").strip()
            if text:
                interactions.append(text)
    return interactions


def _drug_class_names(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        return [name] if name else []
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            names.extend(_drug_class_names(item))
        seen: set[str] = set()
        ordered = []
        for name in names:
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered
    return []


def _split_sections(sections: dict[str, str], keys: list[str]) -> list[str]:
    for key in keys:
        for section_name, section_text in sections.items():
            if key in section_name:
                return _split_text(section_text)
    return []


def _split_text(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"(?:•|\n|;|\.\s{1,})", text)
    return [p.strip() for p in parts if p and p.strip()]


def _source_id_from_url(url: str) -> str | None:
    match = re.search(r"-(\d+)$", url)
    return match.group(1) if match else None


def _slug_name_from_url(url: str) -> str:
    match = re.search(r"/drug/([a-z0-9-]+)-\d+$", url)
    if not match:
        return ""
    slug = match.group(1).replace("-", " ").strip()
    return slug


def _normalize_generic(value: str | None) -> str | None:
    txt = str(value or "").strip()
    if not txt:
        return None
    txt = txt.replace("###", " + ")
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt or None


def _slug_from_url(url: str) -> str | None:
    match = re.search(r"/drug/([a-z0-9-]+-\d+)$", url)
    return match.group(1) if match else None


def _first_non_empty(values: list[str]) -> str | None:
    for value in values:
        txt = str(value or "").strip()
        if txt:
            return txt
    return None


def _to_int(raw: str | None, default: int) -> int:
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default
