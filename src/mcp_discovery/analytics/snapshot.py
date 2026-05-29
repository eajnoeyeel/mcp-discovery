"""Weekly snapshot persistence — per-tool metrics archived by ISO week.

Storage: pluggable backend (local filesystem by default, S3/Supabase via protocol).
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from mcp_discovery.analytics.storage.base import SnapshotBackend


class WeeklySnapshot(BaseModel):
    """Per-tool weekly metrics snapshot."""

    week_id: str = Field(description="ISO week, e.g. '2026-W15'")
    tool_id: str
    selection_count: int = 0
    runner_up_count: int = 0
    win_rate: float = 0.0
    geo_total: float = 0.0
    token_count: int = 0
    extra: dict = Field(default_factory=dict)


class SnapshotStore:
    """Snapshot persistence using a pluggable backend.

    Accepts either a Path (wrapped in LocalSnapshotBackend) or any SnapshotBackend.
    """

    def __init__(
        self,
        snapshot_dir: Path | None = None,
        backend: "SnapshotBackend | None" = None,
    ) -> None:
        if backend is not None:
            self._backend = backend
        elif snapshot_dir is not None:
            from mcp_discovery.analytics.storage.local import LocalSnapshotBackend

            self._backend = LocalSnapshotBackend(snapshot_dir=snapshot_dir)
        else:
            raise ValueError("Either snapshot_dir or backend must be provided")

    async def save(self, snapshot: WeeklySnapshot) -> None:
        """Save a weekly snapshot."""
        await self._backend.save(
            tool_id=snapshot.tool_id,
            week_id=snapshot.week_id,
            data=snapshot.model_dump_json(),
        )
        logger.debug("Saved snapshot {} for {}", snapshot.week_id, snapshot.tool_id)

    async def load(self, tool_id: str) -> list[WeeklySnapshot]:
        """Load all snapshots for a tool, sorted by week ascending."""
        lines = await self._backend.load_all(tool_id)
        snapshots: list[WeeklySnapshot] = []
        for line in lines:
            try:
                snapshots.append(WeeklySnapshot(**json.loads(line)))
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Skipping malformed snapshot: {}", e)
        return snapshots
