"""In-memory TTL cache for operability snapshots. Query-plane safe."""

from __future__ import annotations

import asyncio
import random
import time

import httpx
from loguru import logger

from mcp_discovery.operability.models import ToolOperabilitySnapshot


def _derive_status(r: dict) -> str:
    """Compute lifecycle status from operability metrics."""
    status_map = {
        "active": "active",
        "indexed": "active",
        "pending": "pending",
        "indexing": "pending",
        "failed": "pending",
        "event_failed": "pending",
        "quarantined": "quarantined",
        "unreachable": "unreachable",
        "deprecated": "deprecated",
        "stale": "stale",
    }
    raw_status = r.get("index_status")
    if isinstance(raw_status, str) and raw_status in status_map:
        return status_map[raw_status]

    call_count = r.get("call_count", 0) or 0
    if call_count < 20:
        return "active"
    success_rate = r.get("success_rate")
    if success_rate is not None and success_rate < 0.1:
        return "unreachable"
    timeout_rate = r.get("timeout_rate")
    if timeout_rate is not None and timeout_rate > 0.8:
        return "quarantined"
    return "active"


class OperabilityCache:
    """Module-level singleton. Bulk-fetches all snapshots from Supabase view."""

    TTL_SECONDS = 60
    TTL_JITTER_SECONDS = 10
    MAX_POOL_SIZE_ASSUMPTION = 10_000

    def __init__(self, *, supabase_url: str, supabase_key: str) -> None:
        self._url = supabase_url
        self._key = supabase_key
        self._cache: dict[str, ToolOperabilitySnapshot] = {}
        self._last_refresh: float = 0.0
        self._client: httpx.AsyncClient | None = None
        self._refreshing: bool = False

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=5.0)
        return self._client

    def is_fresh(self) -> bool:
        jitter = random.uniform(-self.TTL_JITTER_SECONDS, self.TTL_JITTER_SECONDS)
        return (time.monotonic() - self._last_refresh) < (self.TTL_SECONDS + jitter)

    async def get_bulk(self, tool_ids: list[str]) -> dict[str, ToolOperabilitySnapshot]:
        if not self.is_fresh() and not self._refreshing:
            self._refreshing = True
            asyncio.create_task(self._background_refresh())
        return {tid: self._cache[tid] for tid in tool_ids if tid in self._cache}

    async def _background_refresh(self) -> None:
        try:
            await self._refresh()
        except Exception:
            pass
        finally:
            self._refreshing = False

    async def _refresh(self) -> None:
        try:
            client = self._get_client()
            resp = await client.get(
                f"{self._url}/rest/v1/tool_operability_view?select=*",
                headers={
                    "apikey": self._key,
                    "Authorization": f"Bearer {self._key}",
                },
            )
            resp.raise_for_status()
            rows = resp.json()
            new_cache: dict[str, ToolOperabilitySnapshot] = {}
            for r in rows:
                try:
                    new_cache[r["tool_id"]] = ToolOperabilitySnapshot(
                        tool_id=r["tool_id"],
                        server_id=r.get("server_id", ""),
                        status=_derive_status(r),
                        call_count=r.get("call_count", 0),
                        call_count_7d=r.get("call_count_7d", 0),
                        success_rate=r.get("success_rate"),
                        success_rate_7d=r.get("success_rate_7d"),
                        timeout_rate=r.get("timeout_rate"),
                        avg_latency_ms=r.get("avg_latency_ms"),
                        p95_latency_ms=r.get("p95_latency_ms"),
                    )
                except Exception:
                    continue
            self._cache = new_cache
            self._last_refresh = time.monotonic()
            logger.info(f"OperabilityCache refreshed: {len(new_cache)} tools")
        except Exception as exc:
            logger.warning(f"OperabilityCache refresh failed, keeping stale: {exc}")
