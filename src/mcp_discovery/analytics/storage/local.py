"""Local filesystem storage backends — for development and testing."""

from __future__ import annotations

import json
import re
from pathlib import Path

import aiofiles
import aiofiles.os
from loguru import logger


def _sanitize_filename(name: str) -> str:
    """Convert tool_id to safe filename."""
    return re.sub(r"[/:]+", "_", name)


class LocalLogStore:
    """Append-only JSONL log storage on local filesystem."""

    def __init__(self, log_dir: Path) -> None:
        self._dir = log_dir

    async def append(self, date_key: str, line: str) -> None:
        await aiofiles.os.makedirs(self._dir, exist_ok=True)
        path = self._dir / f"queries-{date_key}.jsonl"
        async with aiofiles.open(path, "a", encoding="utf-8") as f:
            await f.write(line)

    async def read_lines(self, date_key: str) -> list[str]:
        path = self._dir / f"queries-{date_key}.jsonl"
        if not path.exists():
            return []
        async with aiofiles.open(path, encoding="utf-8") as f:
            content = await f.read()
        return [line for line in content.strip().splitlines() if line.strip()]

    async def list_date_keys(self) -> list[str]:
        if not self._dir.exists():
            return []
        keys: list[str] = []
        for f in sorted(self._dir.glob("queries-*.jsonl")):
            key = f.stem.removeprefix("queries-")
            keys.append(key)
        return keys


class LocalSnapshotBackend:
    """JSONL-based snapshot storage on local filesystem."""

    def __init__(self, snapshot_dir: Path) -> None:
        self._dir = snapshot_dir

    async def save(self, tool_id: str, week_id: str, data: str) -> None:
        await aiofiles.os.makedirs(self._dir, exist_ok=True)
        path = self._dir / f"{_sanitize_filename(tool_id)}.jsonl"

        existing: list[str] = []
        if path.exists():
            async with aiofiles.open(path, encoding="utf-8") as f:
                content = await f.read()
            for line in content.strip().splitlines():
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("week_id") != week_id:
                        existing.append(line)
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed snapshot line in {}", path.name)

        existing.append(data)
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write("\n".join(existing) + "\n")

    async def load_all(self, tool_id: str) -> list[str]:
        path = self._dir / f"{_sanitize_filename(tool_id)}.jsonl"
        if not path.exists():
            return []
        async with aiofiles.open(path, encoding="utf-8") as f:
            content = await f.read()
        lines: list[str] = []
        for line in content.strip().splitlines():
            if line.strip():
                lines.append(line)
        return sorted(lines, key=lambda line: json.loads(line).get("week_id", ""))
