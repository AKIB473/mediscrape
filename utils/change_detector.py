from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import orjson

logger = logging.getLogger(__name__)


class ChangeDetector:
    """Detects whether scraped data has changed since last run."""

    def __init__(self, data_dir: Path = Path("data")):
        self.data_dir = data_dir
        self.checksums_file = data_dir / "checksums.json"

    def load_checksums(self) -> dict[str, str]:
        if not self.checksums_file.exists():
            return {}
        return orjson.loads(self.checksums_file.read_bytes())

    def save_checksums(self, checksums: dict[str, str]):
        self.checksums_file.write_bytes(
            orjson.dumps(checksums, option=orjson.OPT_INDENT_2)
        )

    def has_changed(self, source: str) -> bool:
        checksums = self.load_checksums()
        drugs_file = self.data_dir / source / "drugs.json"
        if not drugs_file.exists():
            return True

        current = hashlib.sha256(drugs_file.read_bytes()).hexdigest()
        previous = checksums.get(source)
        return current != previous

    def update_checksum(self, source: str):
        checksums = self.load_checksums()
        drugs_file = self.data_dir / source / "drugs.json"
        if drugs_file.exists():
            checksums[source] = hashlib.sha256(drugs_file.read_bytes()).hexdigest()
            self.save_checksums(checksums)

    def get_changed_sources(self, sources: list[str]) -> list[str]:
        return [s for s in sources if self.has_changed(s)]
