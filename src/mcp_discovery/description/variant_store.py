"""JSONL persistence for per-client description variants."""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from mcp_discovery.description.base import PerClientVariant, VendorStyle


class VariantStore:
    """Read/write PerClientVariant entries to a JSONL file.

    Supports incremental append and lookup by tool_id + vendor.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def save(self, variant: PerClientVariant) -> None:
        """Append a single variant to the JSONL file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(variant.model_dump_json() + "\n")

    def save_batch(self, variants: list[PerClientVariant]) -> None:
        """Append multiple variants to the JSONL file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            for v in variants:
                f.write(v.model_dump_json() + "\n")
        logger.info(f"Saved {len(variants)} variants to {self._path.name}")

    def load_all(self) -> list[PerClientVariant]:
        """Load all variants from the JSONL file."""
        if not self._path.exists():
            return []
        entries: list[PerClientVariant] = []
        for line in self._path.read_text(encoding="utf-8").strip().splitlines():
            if not line:
                continue
            entries.append(PerClientVariant(**json.loads(line)))
        return entries

    def load_by_tool_id(self, tool_id: str) -> list[PerClientVariant]:
        """Load all variants for a specific tool_id."""
        return [v for v in self.load_all() if v.tool_id == tool_id]

    def exists(self, tool_id: str, vendor: VendorStyle) -> bool:
        """Check if a variant for (tool_id, vendor) already exists.

        TODO: O(n) full-file scan per call — add in-memory cache if called
        in tight loops (acceptable for current experiment scale ~15 entries).
        """
        return any(v.tool_id == tool_id and v.vendor == vendor for v in self.load_all())
