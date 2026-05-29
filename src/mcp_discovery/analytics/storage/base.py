"""Storage protocol definitions for analytics persistence.

Two protocols:
- LogStore: append-only log storage (for QueryLogger)
- SnapshotBackend: key-value snapshot storage (for SnapshotStore)

Local filesystem implementations provided as defaults.
S3/Supabase implementations can be added without changing consumers.
"""

from __future__ import annotations

from typing import Protocol


class LogStore(Protocol):
    """Append-only log storage protocol."""

    async def append(self, date_key: str, line: str) -> None:
        """Append a line to the log for the given date key."""
        ...

    async def read_lines(self, date_key: str) -> list[str]:
        """Read all lines for a date key."""
        ...

    async def list_date_keys(self) -> list[str]:
        """List all available date keys."""
        ...


class SnapshotBackend(Protocol):
    """Key-value snapshot storage protocol."""

    async def save(self, tool_id: str, week_id: str, data: str) -> None:
        """Save a snapshot (as JSON string) for a tool/week."""
        ...

    async def load_all(self, tool_id: str) -> list[str]:
        """Load all snapshot JSON strings for a tool, sorted by week."""
        ...
