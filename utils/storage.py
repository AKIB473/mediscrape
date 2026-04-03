from __future__ import annotations

import hashlib
from pathlib import Path

import orjson


class Storage:
    """Handles reading/writing scraped drug data."""

    def __init__(self, base_dir: Path = Path("data")):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def load_drugs(self, source: str) -> list[dict]:
        path = self.base_dir / source / "drugs.json"
        if not path.exists():
            return []
        return orjson.loads(path.read_bytes())

    def save_drugs(self, source: str, drugs: list[dict]) -> str:
        path = self.base_dir / source / "drugs.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = orjson.dumps(drugs, option=orjson.OPT_INDENT_2)
        path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def load_meta(self, source: str) -> dict | None:
        path = self.base_dir / source / "meta.json"
        if not path.exists():
            return None
        return orjson.loads(path.read_bytes())

    def get_checksum(self, source: str) -> str | None:
        path = self.base_dir / source / "drugs.json"
        if not path.exists():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
