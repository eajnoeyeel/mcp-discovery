"""Demo provider journey — full registration + indexing + search before/after.

Shows CTO demo Segment B:
  1. Register demo-crm server with bad descriptions → index → find_best_tool (low rank)
  2. Re-register with enriched descriptions → re-index → find_best_tool (high rank)

Run:
  uv run python scripts/demo_provider_journey.py

Prerequisites:
  - SAM local NOT required — uses direct IndexService + FlatStrategy
  - .env must have: OPENAI_API_KEY, QDRANT_URL, QDRANT_API_KEY
  - SUPABASE_URL + SUPABASE_SERVICE_KEY optional (gracefully skipped if absent)
"""

# ruff: noqa: E402

import asyncio
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in [str(_ROOT), str(_ROOT / "src"), str(_ROOT / "mlp")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from dotenv import load_dotenv

load_dotenv()

from loguru import logger
from qdrant_client import AsyncQdrantClient

from mcp_discovery.config import Settings
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder
from mcp_discovery.models import SearchResult
from mcp_discovery.pipeline.flat import FlatStrategy
from mcp_discovery.reranking.cohere_reranker import CohereReranker
from mcp_discovery.retrieval.qdrant_store import QdrantStore
from service.services.index_service import IndexService

# ---------------------------------------------------------------------------
# Demo server definition
# ---------------------------------------------------------------------------

DEMO_SERVER_ID = "demo-crm"
DEMO_SERVER_NAME = "Demo CRM — Customer Records"
DEMO_SERVER_URL = "https://demo.example.com/mcp"
QUERY = "테이블에서 조건에 맞는 레코드 찾아줘"

TOOLS_ORIGINAL: list[dict] = [
    {
        "tool_id": "demo-crm::find_records",
        "server_id": DEMO_SERVER_ID,
        "tool_name": "find_records",
        "description": "Find data",
    },
    {
        "tool_id": "demo-crm::list_contacts",
        "server_id": DEMO_SERVER_ID,
        "tool_name": "list_contacts",
        "description": "List items",
    },
    {
        "tool_id": "demo-crm::create_record",
        "server_id": DEMO_SERVER_ID,
        "tool_name": "create_record",
        "description": "Create entry",
    },
]

TOOLS_ENRICHED: list[dict] = [
    {
        "tool_id": "demo-crm::find_records",
        "server_id": DEMO_SERVER_ID,
        "tool_name": "find_records",
        "description": (
            "Search and filter CRM records by field value, "
            "useful for finding contacts, deals, or activities matching specific criteria"
        ),
    },
    {
        "tool_id": "demo-crm::list_contacts",
        "server_id": DEMO_SERVER_ID,
        "tool_name": "list_contacts",
        "description": (
            "Retrieve a paginated list of CRM contacts with optional "
            "filtering by status, company, or last activity date"
        ),
    },
    {
        "tool_id": "demo-crm::create_record",
        "server_id": DEMO_SERVER_ID,
        "tool_name": "create_record",
        "description": (
            "Create a new CRM record such as contact, deal, or activity "
            "with specified field values in the target database table"
        ),
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_services(settings: Settings) -> tuple[FlatStrategy, IndexService]:
    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )
    tool_store = QdrantStore(client=client, collection_name="mcp_tools")
    reranker: CohereReranker | None = None
    legacy_rerank_api_key = os.getenv("COHERE_API_KEY")
    if legacy_rerank_api_key:
        try:
            reranker = CohereReranker(
                api_key=legacy_rerank_api_key,
                model=os.getenv("RERANK_MODEL", "rerank-v3.5"),
            )
        except RuntimeError as exc:
            logger.warning(f"Legacy reranker unavailable; running without reranker: {exc}")
    strategy = FlatStrategy(embedder=embedder, tool_store=tool_store, reranker=reranker)
    index_svc = IndexService(embedder=embedder, qdrant_store=tool_store)
    return strategy, index_svc


async def _upsert_to_supabase(tools: list[dict]) -> None:
    """Upsert demo tools to Supabase with index_status=pending. Non-fatal if missing."""
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not supabase_url or not supabase_key:
        logger.info("Supabase creds not set — skipping Supabase upsert (Qdrant-only mode)")
        return

    import httpx

    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }
    async with httpx.AsyncClient() as client:
        server_row = {
            "server_id": DEMO_SERVER_ID,
            "name": DEMO_SERVER_NAME,
            "description": "Demo CRM provider for MCP Discovery platform demo",
            "url": DEMO_SERVER_URL,
            "tags": ["demo", "crm"],
        }
        r = await client.post(
            f"{supabase_url}/rest/v1/mcp_servers",
            headers=headers,
            json=server_row,
            params={"on_conflict": "server_id"},
            timeout=10.0,
        )
        r.raise_for_status()

        tool_rows = [{**t, "index_status": "pending"} for t in tools]
        r = await client.post(
            f"{supabase_url}/rest/v1/mcp_tools",
            headers=headers,
            json=tool_rows,
            params={"on_conflict": "tool_id"},
            timeout=10.0,
        )
        r.raise_for_status()
        logger.info(f"Upserted {len(tool_rows)} tools to Supabase")


def _render_results(results: list[SearchResult], label: str) -> str:
    lines = [f"\n{'=' * 62}", f"  {label}", f"{'=' * 62}"]
    for r in results:
        marker = " <<<" if "demo-crm" in r.tool.tool_id else ""
        desc = (r.tool.description or "_no description_")[:65]
        lines.append(f"  #{r.rank:<2} {r.tool.tool_id:<38} {r.score:.4f}{marker}")
        lines.append(f"       {desc}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    logger.info("=== Demo Provider Journey — CTO Demo Segment B ===")
    settings = Settings()
    strategy, index_svc = _build_services(settings)

    # Step 1: Register with BAD descriptions
    logger.info("STEP 1: Register demo-crm with ORIGINAL (bad) descriptions")
    await _upsert_to_supabase(TOOLS_ORIGINAL)
    indexed = await index_svc.index_rows(TOOLS_ORIGINAL)
    logger.info(f"Indexed {indexed} tools with ORIGINAL descriptions")

    # Step 2: Search BEFORE enrichment
    logger.info(f"STEP 2: find_best_tool query='{QUERY}' [BEFORE enrichment]")
    results_before = await strategy.search(QUERY, top_k=8)
    print(_render_results(results_before, f"BEFORE enrichment — query: {QUERY}"))

    # Step 3: Re-register with ENRICHED descriptions
    logger.info("STEP 3: Re-register demo-crm with ENRICHED descriptions")
    await _upsert_to_supabase(TOOLS_ENRICHED)
    indexed = await index_svc.index_rows(TOOLS_ENRICHED)
    logger.info(f"Re-indexed {indexed} tools with ENRICHED descriptions")

    # Step 4: Search AFTER enrichment
    logger.info(f"STEP 4: find_best_tool query='{QUERY}' [AFTER enrichment]")
    results_after = await strategy.search(QUERY, top_k=8)
    print(_render_results(results_after, f"AFTER enrichment — query: {QUERY}"))

    # Summary
    before_demo = next((r for r in results_before if "demo-crm" in r.tool.tool_id), None)
    after_find = next(
        (r for r in results_after if r.tool.tool_id == "demo-crm::find_records"), None
    )
    print(f"\n{'=' * 62}")
    print("  SUMMARY")
    print(f"{'=' * 62}")
    if before_demo:
        print(
            f"  demo-crm::find_records  BEFORE: rank #{before_demo.rank}"
            f"  score {before_demo.score:.4f}"
        )
    else:
        print("  demo-crm::find_records  BEFORE: not in top 8")
    if after_find:
        print(
            f"  demo-crm::find_records  AFTER:  rank #{after_find.rank}"
            f"  score {after_find.score:.4f}"
        )
    else:
        print("  demo-crm::find_records  AFTER:  not in top 8")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    asyncio.run(main())
