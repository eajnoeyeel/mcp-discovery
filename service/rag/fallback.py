"""Supabase full-text search fallback for degraded mode."""

import httpx
from loguru import logger

from mcp_discovery.models import MCPTool, SearchResult

# Ceiling for fallback scores so they never outrank confident semantic results.
# Formula: score = (1 / rank) * DEGRADED_SCORE_CEILING
# rank 1 = 0.5, rank 2 = 0.25, rank 3 ≈ 0.167
# Max composite after w_rel=0.75: 0.5 * 0.75 = 0.375 < semantic 0.6 * 0.75 = 0.45
DEGRADED_SCORE_CEILING = 0.5


class SupabaseFallback:
    """Lexical search via Supabase RPC (tsvector).

    Used in degraded mode when Qdrant is unavailable.
    Searches indexed tools in the full catalog via FTS.
    """

    def __init__(
        self,
        supabase_url: str,
        supabase_key: str,
        timeout: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = supabase_url
        self._key = supabase_key
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None
        self._headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
            "Content-Type": "application/json",
        }

    @property
    def is_configured(self) -> bool:
        return bool(self._url and self._key)

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Search indexed tools (backward-compatible default)."""
        return await self._search(query, limit=limit, status_filter=None)

    async def search_pending_freshness(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Search only pending (not yet indexed) tools for freshness supplement."""
        return await self._search(query, limit=limit, status_filter="pending")

    async def search_full_catalog(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Search full catalog without status filter (degraded mode)."""
        return await self._search(query, limit=limit, status_filter=None)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _search(
        self,
        query: str,
        limit: int,
        status_filter: str | None,
    ) -> list[SearchResult]:
        if not self.is_configured:
            return []
        payload: dict = {"search_query": query, "result_limit": limit}
        if status_filter is not None:
            payload["status_filter"] = status_filter
        try:
            client = self._get_client()
            resp = await client.post(
                f"{self._url}/rest/v1/rpc/search_tools_fts",
                headers=self._headers,
                json=payload,
            )
            resp.raise_for_status()
            rows = resp.json()
        except Exception as e:
            logger.warning(f"Supabase fallback failed: {e}")
            return []
        return [
            SearchResult(
                tool=MCPTool(
                    server_id=r["server_id"],
                    tool_name=r["tool_name"],
                    tool_id=r["tool_id"],
                    description=r.get("description"),
                    input_schema=r.get("input_schema"),
                ),
                score=round((1.0 / (i + 1)) * DEGRADED_SCORE_CEILING, 4),
                rank=i + 1,
                source_path="freshness" if status_filter == "pending" else "lexical_fallback",
            )
            for i, r in enumerate(rows)
        ]
