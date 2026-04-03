from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import orjson

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scrapers.international.who_eml import WHOEMLScraper


class _DummyResponse:
    def __init__(self, body: bytes):
        self.body = body
        self.text = ""


class _WHOFetcherStub(WHOEMLScraper):
    async def fetch_page(self, url: str, **kwargs):
        payload = {
            "@id": "/medicines/205",
            "name": "BCG vaccine",
            "nonProprietaryName": "BCG vaccine",
            "activeIngredient": ["bcg vaccine"],
            "description": "<p>Essential medicine</p>",
            "sameAs": "https://example.org/med",
            "status": "AddedToEml",
            "drugUnit": ["vial"],
            "guideline": [{"@id": "/recommendations/263"}],
        }
        return _DummyResponse(orjson.dumps(payload))


def test_parse_medicine_jsonld_maps_core_fields(tmp_path: Path):
    scraper = WHOEMLScraper(data_dir=tmp_path)
    data = {
        "@id": "/medicines/205",
        "name": "BCG vaccine",
        "nonProprietaryName": "BCG vaccine",
        "activeIngredient": ["bcg vaccine"],
        "description": "<div><p>Essential medicine</p></div>",
        "sameAs": "https://example.org/med",
        "status": "AddedToEml",
        "drugUnit": ["vial"],
        "guideline": [{"@id": "/recommendations/263"}],
    }

    drug = scraper._parse_medicine_jsonld(data, "https://list.essentialmeds.org/medicines/205")

    assert drug is not None
    assert drug.source == "who_eml"
    assert drug.source_id == "205"
    assert drug.generic_name == "BCG vaccine"
    assert drug.description == "Essential medicine"
    assert drug.extra["status"] == "AddedToEml"
    assert drug.extra["guideline_refs"] == ["/recommendations/263"]


def test_fetch_medicine_jsonld_uses_response_body_when_text_empty(tmp_path: Path):
    scraper = _WHOFetcherStub(data_dir=tmp_path)

    data = asyncio.run(scraper._fetch_medicine_jsonld("https://list.essentialmeds.org/medicines/205"))

    assert data is not None
    assert data["name"] == "BCG vaccine"
