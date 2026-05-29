"""Index Lambda thin adapter around the shared index service."""

import os

os.environ.setdefault("HF_HOME", "/var/task/.cache/fastembed")

import json
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger
from qdrant_client import AsyncQdrantClient

from mcp_discovery.config import Settings
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder
from mcp_discovery.retrieval.qdrant_store import QdrantStore
from service.adapters.supabase_client import SupabaseClient
from service.services.contracts import IndexRequest
from service.services.index_service import IndexService
from service.shared.http import error_response, json_response

settings = Settings()
embedder = OpenAIEmbedder(
    api_key=settings.openai_api_key or "",
    model=settings.embedding_model,
    dimension=settings.embedding_dimension,
)
qdrant_store = QdrantStore(
    client=AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key),
    collection_name=settings.qdrant_collection_name,
)

_SPARSE: object | None = None
_LLM: object | None = None
_CACHE: object | None = None
_INDEX_SVC: object | None = None


def _get_sparse() -> object | None:
    global _SPARSE
    if _SPARSE is None:
        try:
            from mcp_discovery.embedding.fastembed_sparse import FastEmbedSparseEmbedder

            _SPARSE = FastEmbedSparseEmbedder()
        except ImportError:
            logger.warning("fastembed not installed — sparse embedder disabled for index")
    return _SPARSE


def _get_llm() -> object | None:
    global _LLM
    if _LLM is None:
        try:
            from openai import AsyncOpenAI

            _LLM = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        except (ImportError, KeyError):
            logger.warning("OpenAI not available — LLM enrichment disabled")
    return _LLM


def _get_cache() -> object | None:
    global _CACHE
    if _CACHE is None:
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
        if supabase_url and supabase_key:
            from service.adapters.enrichment_cache import EnrichmentCache

            _CACHE = EnrichmentCache(supabase_url=supabase_url, supabase_key=supabase_key)
    return _CACHE


index_service = IndexService(
    embedder=embedder,
    qdrant_store=qdrant_store,
    sparse_embedder=_get_sparse(),
    llm_client=_get_llm(),
    enrichment_cache=_get_cache(),
    enrichment_disabled=os.environ.get("ENRICHMENT_DISABLED", "false").lower() == "true",
)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
SUPABASE_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}


def _build_supabase_client() -> SupabaseClient:
    """Build a SupabaseClient from module-level config."""
    return SupabaseClient(url=SUPABASE_URL, service_key=SUPABASE_SERVICE_KEY)


async def _fetch_pending_tools(server_id: str) -> list[dict]:
    url = f"{SUPABASE_URL}/rest/v1/mcp_tools"
    params = {"server_id": f"eq.{server_id}", "index_status": "eq.pending", "select": "*"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=SUPABASE_HEADERS, params=params, timeout=10.0)
        resp.raise_for_status()
        return resp.json()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _update_tool_status(
    tool_ids: list[str], status: str, *, indexed_at: str | None = None
) -> None:
    if not tool_ids:
        return
    url = f"{SUPABASE_URL}/rest/v1/mcp_tools"
    params = {"tool_id": f"in.({','.join(tool_ids)})"}
    payload = {"index_status": status}
    if indexed_at is not None:
        payload["last_indexed_at"] = indexed_at
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            url,
            headers=SUPABASE_HEADERS,
            params=params,
            json=payload,
            timeout=10.0,
        )
        resp.raise_for_status()
        logger.info(f"Updated {len(tool_ids)} tool(s) to status={status!r}")


async def _fetch_tool_statuses(server_id: str) -> list[str]:
    url = f"{SUPABASE_URL}/rest/v1/mcp_tools"
    params = {"server_id": f"eq.{server_id}", "select": "index_status"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=SUPABASE_HEADERS, params=params, timeout=10.0)
        resp.raise_for_status()
        return [row.get("index_status", "") for row in resp.json()]


async def _update_server_status(server_id: str, status: str) -> None:
    url = f"{SUPABASE_URL}/rest/v1/mcp_servers"
    params = {"server_id": f"eq.{server_id}"}
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            url,
            headers=SUPABASE_HEADERS,
            params=params,
            json={"index_status": status},
            timeout=10.0,
        )
        resp.raise_for_status()
        logger.info(f"Updated server {server_id!r} to index_status={status!r}")


async def _finalize_server_status(server_id: str) -> None:
    statuses = await _fetch_tool_statuses(server_id)
    if not statuses:
        return
    if all(status == "indexed" for status in statuses):
        await _update_server_status(server_id, "indexed")
    elif any(status == "failed" for status in statuses):
        await _update_server_status(server_id, "failed")


async def _claim_pending_tools(tool_ids: list[str]) -> int:
    """Atomically claim pending tools by setting status to 'indexing'.

    Uses an optimistic lock by filtering on ``index_status=eq.pending`` so that
    only rows still in the pending state are transitioned.  If another Lambda
    invocation already claimed the same batch, the filter will match 0 rows and
    the function returns 0, allowing the caller to skip processing gracefully.

    Returns the number of rows actually claimed.
    """
    if not tool_ids:
        return 0
    url = f"{SUPABASE_URL}/rest/v1/mcp_tools"
    params = {
        "tool_id": f"in.({','.join(tool_ids)})",
        "index_status": "eq.pending",  # Only claim if still pending
    }
    headers = {
        **SUPABASE_HEADERS,
        "Prefer": "return=representation",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            url,
            headers=headers,
            params=params,
            json={"index_status": "indexing"},
            timeout=10.0,
        )
        resp.raise_for_status()
        claimed = resp.json()
        return len(claimed)


async def _mark_failed_safe(tool_ids: list[str]) -> None:
    """Mark tools as failed, swallowing any status-update errors."""
    if not tool_ids:
        return
    try:
        await _update_tool_status(tool_ids, "failed")
    except Exception as e:
        logger.error(f"Failed to mark tools as failed: {e}")


async def _async_handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    detail = event.get("detail", {})

    try:
        if isinstance(detail, str):
            detail = json.loads(detail)
        request = IndexRequest.model_validate(detail)
    except Exception as exc:
        logger.error(f"Invalid index event: {exc}")
        return error_response(400, str(exc))

    rows: list[dict] = []
    try:
        rows = await _fetch_pending_tools(request.server_id)
        if not rows:
            await _finalize_server_status(request.server_id)
            return json_response(
                200,
                {"server_id": request.server_id, "indexed_count": 0, "skipped_count": 0},
            )

        tool_ids = [row["tool_id"] for row in rows]
        claimed_count = await _claim_pending_tools(tool_ids)
        if claimed_count == 0:
            logger.info(
                f"No pending tools to claim for server_id={request.server_id} (already claimed)"
            )
            return json_response(
                200,
                {
                    "server_id": request.server_id,
                    "indexed_count": 0,
                    "skipped_count": 0,
                    "already_claimed": True,
                },
            )

        rows_to_index, skipped_tool_ids = await index_service.split_rows_by_content_hash(rows)
        indexed_count = 0
        indexed_tool_ids: list[str] = []
        if rows_to_index:
            indexed_count = await index_service.index_rows(rows_to_index)
            indexed_tool_ids = [row["tool_id"] for row in rows_to_index]
            await _update_tool_status(indexed_tool_ids, "indexed", indexed_at=_utc_now_iso())
        if skipped_tool_ids:
            await _update_tool_status(skipped_tool_ids, "indexed", indexed_at=_utc_now_iso())
        await _finalize_server_status(request.server_id)
        return json_response(
            200,
            {
                "server_id": request.server_id,
                "indexed_count": indexed_count,
                "skipped_count": len(skipped_tool_ids),
            },
        )
    except Exception as exc:
        logger.error(f"Indexing failed for server_id={request.server_id}: {exc}")
        tool_ids = [row["tool_id"] for row in rows]
        await _mark_failed_safe(tool_ids)
        await _finalize_server_status(request.server_id)
        return error_response(500, str(exc))


def lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """AWS Lambda entry point."""
    from service.shared.event_loop import get_or_create_loop

    loop = get_or_create_loop()
    return loop.run_until_complete(_async_handler(event, context))
