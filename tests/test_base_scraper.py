from __future__ import annotations

import asyncio
from pathlib import Path
import sys

import orjson

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.drug import Drug
from scrapers.base import BaseScraper


class _FailingScraper(BaseScraper):
    name = "failing"

    async def scrape_all(self):
        raise RuntimeError("boom")
        yield Drug(source=self.name, source_url="https://example.com")


class _EmptyScraper(BaseScraper):
    name = "empty"

    def __init__(self, data_dir: Path):
        super().__init__(data_dir=data_dir)
        self.client = _DummyAsyncClosable()
        self.fetcher = _DummySyncClosable()

    async def scrape_all(self):
        if False:
            yield Drug(source=self.name, source_url="https://example.com")


class _DummyAsyncClosable:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


class _DummySyncClosable:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_failed_empty_run_preserves_existing_drugs_file(tmp_path: Path):
    source_dir = tmp_path / "failing"
    source_dir.mkdir(parents=True, exist_ok=True)
    drugs_file = source_dir / "drugs.json"
    original_data = [{"source": "seed", "source_url": "https://example.com"}]
    drugs_file.write_bytes(orjson.dumps(original_data))
    original_checksum = BaseScraper._file_checksum(drugs_file)

    scraper = _FailingScraper(data_dir=tmp_path)
    meta = asyncio.run(scraper.run())

    assert meta.errors == 1
    assert meta.total_drugs == 0
    assert BaseScraper._file_checksum(drugs_file) == original_checksum
    assert orjson.loads(drugs_file.read_bytes()) == original_data


def test_run_closes_async_and_sync_resources(tmp_path: Path):
    scraper = _EmptyScraper(data_dir=tmp_path)

    meta = asyncio.run(scraper.run())

    assert meta.errors == 0
    assert meta.total_drugs == 0
    assert scraper.client.closed is True
    assert scraper.fetcher.closed is True
