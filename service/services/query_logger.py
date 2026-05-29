"""Fire-and-forget query logging to Supabase query_logs.

Control-plane concern — failures must never affect the hot path.
Uses shared httpx.AsyncClient (lazy singleton, not per-request).
"""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger


class QueryLogger:
    """Logs search queries to Supabase. Fire-and-forget."""

    def __init__(self, *, supabase_url: str, supabase_key: str) -> None:
        self._url = supabase_url
        self._key = supabase_key
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy singleton — reuse across requests."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=3.0)
        return self._client

    def _build_payload(
        self,
        *,
        event_id: str,
        query: str,
        results: list[dict[str, Any]],
        confidence: float,
        strategy: str,
        latency_ms: float,
        stage_metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build payload matching query_logs DDL exactly."""
        top = results[0] if results else {}
        return {
            "event_id": event_id,
            "query": query,
            "recommended_tool_id": top.get("tool_id"),
            "confidence": confidence,
            "latency_ms": round(latency_ms, 1),
            "strategy": strategy,
            "alternatives": results[:5],
            "stage_metrics": stage_metrics,
        }

    async def log_query(
        self,
        *,
        event_id: str,
        query: str,
        results: list[dict[str, Any]],
        confidence: float,
        strategy: str,
        latency_ms: float,
        client_id: str | None = None,
        stage_metrics: dict[str, Any] | None = None,
    ) -> int | None:
        """Fire-and-forget query log write.

        INSERTs to query_logs and returns the inserted row's id on success,
        or None on failure. Never raises — failures are logged as warnings.

        The inserted id is captured so that the bridge handler can correlate
        subsequent execute_tool calls via execution_logs.query_log_id FK.
        """
        payload = self._build_payload(
            event_id=event_id,
            query=query,
            results=results,
            confidence=confidence,
            strategy=strategy,
            latency_ms=latency_ms,
            stage_metrics=stage_metrics,
        )
        if client_id:
            payload["client_id"] = client_id
        try:
            client = self._get_client()
            resp = await client.post(
                f"{self._url}/rest/v1/query_logs",
                headers={
                    "apikey": self._key,
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                return int(data[0].get("id"))
            return None
        except Exception as exc:
            logger.warning(f"Query log failed (non-blocking): {exc}")
            return None
