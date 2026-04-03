"""RxList scraper - rxlist.com - US prescribing info (by WebMD)."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator

from models.drug import Drug
from scrapers.base import BaseScrapingScraper

logger = logging.getLogger(__name__)


class RxListScraper(BaseScrapingScraper):
    name = "rxlist"
    base_url = "https://www.rxlist.com"
    rate_limit = 2.0
    use_stealth = True

    async def scrape_all(self) -> AsyncIterator[Drug]:
        urls = await self._get_all_drug_urls()
        logger.info(f"RxList: found {len(urls)} drug URLs")

        for url in urls:
            try:
                drug = await self._scrape_drug_page(url)
                if drug:
                    yield drug
            except Exception as e:
                logger.warning(f"RxList: error scraping {url}: {e}")

    async def _get_all_drug_urls(self) -> list[str]:
        urls = set()
        for letter in "abcdefghijklmnopqrstuvwxyz":
            try:
                page = await self.fetch_page(f"{self.base_url}/drugs/alpha_{letter}.htm")
                for link in page.css('a[href*="/drug/"], a[href$=".htm"]'):
                    href = link.attrib.get("href", "")
                    if href and "/drug/" in href:
                        full = href if href.startswith("http") else f"{self.base_url}{href}"
                        urls.add(full)
            except Exception:
                pass
        return list(urls)

    async def _scrape_drug_page(self, url: str) -> Drug | None:
        page = await self.fetch_page(url)
        jsonld = self.extract_jsonld(page)

        title = _text(page.css_first("h1"))
        if not title:
            return None

        generic_name = _text(page.css_first(".drug-generic-name, [class*=generic]"))

        sections = {}
        for h2 in page.css("h2, h3"):
            key = _text(h2).lower()
            content = []
            nxt = h2
            for _ in range(30):
                nxt = nxt.css_first("+ p, + ul, + ol, + div")
                if nxt is None:
                    break
                t = _text(nxt)
                if t:
                    content.append(t)
            if content:
                sections[key] = "\n".join(content)

        # Side effects list
        side_effects = []
        se_elem = page.css_first('[id*="sideEffects"], [id*="side_effects"]')
        if se_elem:
            for li in se_elem.css("li"):
                side_effects.append(_text(li))

        return Drug(
            source="rxlist",
            source_url=url,
            brand_name=title.split("(")[0].strip() if "(" in title else title,
            generic_name=generic_name or (title.split("(")[1].rstrip(")") if "(" in title else ""),
            description=sections.get("description", sections.get("what is", "")),
            indications=_split(sections.get("indications", sections.get("uses", ""))),
            dosage=sections.get("dosage", sections.get("dosage and administration", "")),
            side_effects=side_effects or _split(sections.get("side effects", "")),
            warnings=_split(sections.get("warnings", sections.get("warnings and precautions", ""))),
            contraindications=_split(sections.get("contraindications", "")),
            interactions=_split(sections.get("drug interactions", sections.get("interactions", ""))),
            mechanism_of_action=sections.get("clinical pharmacology", sections.get("mechanism of action", "")),
            overdose=sections.get("overdosage", sections.get("overdose", "")),
            pregnancy_category=sections.get("use in pregnancy", sections.get("pregnancy", "")),
            storage=sections.get("how supplied", sections.get("storage", "")),
            extra={
                "jsonld": jsonld,
                "sections": sections,
                "patient_info": sections.get("patient information", ""),
                "how_supplied": sections.get("how supplied", ""),
            },
        )


def _text(elem) -> str:
    if elem is None:
        return ""
    return elem.text.strip() if hasattr(elem, "text") and elem.text else ""


def _split(text: str) -> list[str]:
    if not text:
        return []
    return [i.strip() for i in re.split(r"[•\n]", text) if i.strip()]
