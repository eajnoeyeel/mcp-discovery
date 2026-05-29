"""Supabase adapter for tool_enrichment_cache — ADR-0017 P5 idempotency."""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from mcp_discovery.indexing.enrichment import EnrichedDescription


class EnrichmentCache:
    def __init__(self, *, supabase_url: str, supabase_key: str) -> None:
        self._url = supabase_url
        self._key = supabase_key
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=3.0)
        return self._client

    async def get(self, content_hash: str) -> dict[str, Any] | None:
        r = await self._get_client().get(
            f"{self._url}/rest/v1/tool_enrichment_cache",
            params={"content_hash": f"eq.{content_hash}", "select": "*"},
            headers={"apikey": self._key, "Authorization": f"Bearer {self._key}"},
        )
        if r.status_code >= 400:
            logger.warning(f"enrichment_cache GET {r.status_code}: {r.text[:200]}")
            return None
        items = r.json()
        return items[0] if items else None

    async def put(self, content_hash: str, *, tool_id: str, enriched: EnrichedDescription) -> None:
        r = await self._get_client().post(
            f"{self._url}/rest/v1/tool_enrichment_cache",
            json={
                "content_hash": content_hash,
                "tool_id": tool_id,
                "sparse_input": enriched.sparse_input,
                "enrichment_model": enriched.model,
            },
            headers={
                "apikey": self._key,
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates",
            },
        )
        if r.status_code >= 400 and r.status_code != 409:
            logger.warning(f"enrichment_cache PUT {r.status_code}: {r.text[:200]}")

    async def delete(self, content_hash: str) -> None:
        await self._get_client().delete(
            f"{self._url}/rest/v1/tool_enrichment_cache",
            params={"content_hash": f"eq.{content_hash}"},
            headers={"apikey": self._key, "Authorization": f"Bearer {self._key}"},
        )
