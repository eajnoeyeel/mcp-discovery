"""Query logger — daily JSONL files for pipeline query events."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from mcp_discovery.analytics.storage.base import LogStore


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CandidateScore(BaseModel):
    """Score breakdown for a single candidate in a query result."""

    tool_id: str
    score: float = Field(description="Final fused/reranked score")
    dense_score: float | None = Field(default=None, description="Dense channel score")
    sparse_score: float | None = Field(default=None, description="Sparse channel score")


class QueryLogEntry(BaseModel):
    """A single query event recorded by the pipeline."""

    model_config = ConfigDict(populate_by_name=True)

    timestamp: str = Field(default_factory=_utc_now_iso)
    query: str
    # Renamed from selected_tool_id; alias preserved for backward JSONL compatibility.
    # model_dump() -> "recommended_tool_id"; model_dump(by_alias=True) -> "selected_tool_id".
    recommended_tool_id: str = Field(alias="selected_tool_id")
    server_id: str
    confidence: float
    disambiguation_needed: bool
    strategy: str
    latency_ms: float
    alternatives: list[str] = Field(default_factory=list)
    candidates: list[CandidateScore] = Field(default_factory=list)


class QueryLogger:
    """Append query events to a LogStore backend.

    Accepts either a Path (wrapped in LocalLogStore for backward compat)
    or any LogStore implementation.
    """

    def __init__(self, log_dir: Path | None = None, store: "LogStore | None" = None) -> None:
        if store is not None:
            self._store = store
        elif log_dir is not None:
            from mcp_discovery.analytics.storage.local import LocalLogStore

            self._store = LocalLogStore(log_dir=log_dir)
        else:
            raise ValueError("Either log_dir or store must be provided")

    async def log(self, entry: QueryLogEntry) -> QueryLogEntry:
        """Append entry to today's log."""
        date_key = datetime.now(timezone.utc).date().isoformat()
        line = entry.model_dump_json() + "\n"
        await self._store.append(date_key, line)
        return entry

    async def read_logs(self, days: int | None = None) -> list[QueryLogEntry]:
        """Read log entries, optionally filtered to last N days."""
        all_keys = await self._store.list_date_keys()
        if days is not None:
            cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days - 1)).isoformat()
            all_keys = [k for k in all_keys if k >= cutoff]

        entries: list[QueryLogEntry] = []
        for key in sorted(all_keys):
            lines = await self._store.read_lines(key)
            for line in lines:
                if not line.strip():
                    continue
                try:
                    entries.append(QueryLogEntry(**json.loads(line)))
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning("Skipping malformed JSONL line: {}", e)
        return entries
