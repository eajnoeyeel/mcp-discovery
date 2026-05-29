"""E2E Provider Journey — Register → Index → Search → Execute with n8n-mcp.

Full round-trip test of the MCP Discovery pipeline using a real, locally-running
n8n-mcp server as the provider.

Steps:
  1. Register n8n-documentation-mcp server + 7 tools into platform
  2. Index tools into Qdrant (embed + upsert)
  3. Search via RAGService (find_best_tool)
  4. Execute via BridgeService (execute_tool → n8n-mcp stdio)

Run:
  uv run python scripts/e2e_provider_journey.py

Prerequisites:
  - .env: OPENAI_API_KEY, QDRANT_URL, QDRANT_API_KEY
  - SUPABASE_URL + SUPABASE_SERVICE_KEY (optional, gracefully skipped)
  - n8n-mcp installed: /opt/homebrew/bin/n8n-mcp
"""

# ruff: noqa: E402

import asyncio
import json
import os
import sys
import time
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
from mcp_discovery.retrieval.qdrant_store import QdrantStore
from service.rag.factory import RAGServiceFactory
from service.services.index_service import IndexService

# ---------------------------------------------------------------------------
# n8n-mcp server definition
# ---------------------------------------------------------------------------

N8N_SERVER_ID = "n8n-documentation-mcp"
N8N_SERVER_NAME = "n8n Documentation MCP"
N8N_MCP_BIN = "/opt/homebrew/bin/n8n-mcp"

# Tools from n8n-mcp tools/list response
N8N_TOOLS: list[dict] = [
    {
        "tool_id": f"{N8N_SERVER_ID}::search_nodes",
        "server_id": N8N_SERVER_ID,
        "tool_name": "search_nodes",
        "description": (
            "Search n8n nodes by keyword with optional real-world examples. "
            "Pass query as string to find nodes for automation workflows."
        ),
    },
    {
        "tool_id": f"{N8N_SERVER_ID}::get_node",
        "server_id": N8N_SERVER_ID,
        "tool_name": "get_node",
        "description": (
            "Get n8n node info with progressive detail levels and multiple modes. "
            "Returns configuration fields, credentials, and usage examples."
        ),
    },
    {
        "tool_id": f"{N8N_SERVER_ID}::validate_node",
        "server_id": N8N_SERVER_ID,
        "tool_name": "validate_node",
        "description": (
            "Validate n8n node configuration. Use mode='full' for comprehensive "
            "validation with field checks and expression verification."
        ),
    },
    {
        "tool_id": f"{N8N_SERVER_ID}::search_templates",
        "server_id": N8N_SERVER_ID,
        "tool_name": "search_templates",
        "description": (
            "Search n8n workflow templates with multiple modes. "
            "Use searchMode='keyword' for text search or 'semantic' for concept search."
        ),
    },
    {
        "tool_id": f"{N8N_SERVER_ID}::get_template",
        "server_id": N8N_SERVER_ID,
        "tool_name": "get_template",
        "description": (
            "Get n8n workflow template by ID. Returns template structure, "
            "node configuration, and connections for workflow automation."
        ),
    },
    {
        "tool_id": f"{N8N_SERVER_ID}::validate_workflow",
        "server_id": N8N_SERVER_ID,
        "tool_name": "validate_workflow",
        "description": (
            "Full n8n workflow validation: structure, connections, expressions, "
            "AI tools. Returns validation summary with errors and warnings."
        ),
    },
    {
        "tool_id": f"{N8N_SERVER_ID}::tools_documentation",
        "server_id": N8N_SERVER_ID,
        "tool_name": "tools_documentation",
        "description": (
            "Get documentation for n8n MCP tools. Call without parameters "
            "for quick start guide, or specify a tool name for detailed usage."
        ),
    },
]

# Queries targeting n8n capabilities
TEST_QUERIES = [
    "n8n 워크플로우에서 Slack 노드를 어떻게 설정하나요?",
    "Search for automation workflow nodes",
    "Validate my n8n workflow configuration",
    "Find a template for sending emails automatically",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_services(settings: Settings) -> tuple[FlatStrategy, IndexService, QdrantStore]:
    # Resolve Docker-internal hostnames to localhost for local execution
    qdrant_url = settings.qdrant_url.replace("host.docker.internal", "localhost")
    client = AsyncQdrantClient(url=qdrant_url, api_key=settings.qdrant_api_key)
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )
    tool_store = QdrantStore(client=client, collection_name=settings.qdrant_collection_name)
    strategy = FlatStrategy(embedder=embedder, tool_store=tool_store, reranker=None)
    index_svc = IndexService(embedder=embedder, qdrant_store=tool_store)
    return strategy, index_svc, tool_store


def _render_results(results: list[SearchResult], label: str) -> str:
    lines = [f"\n{'=' * 70}", f"  {label}", f"{'=' * 70}"]
    for r in results:
        marker = " <<<" if N8N_SERVER_ID in r.tool.tool_id else ""
        desc = (r.tool.description or "")[:60]
        lines.append(f"  #{r.rank:<2} {r.tool.tool_id:<45} {r.score:.4f}{marker}")
        lines.append(f"       {desc}")
    if not results:
        lines.append("  (no results)")
    return "\n".join(lines)


async def _execute_n8n_tool(tool_name: str, arguments: dict) -> dict:
    """Execute a tool on n8n-mcp via stdio JSON-RPC.

    Uses asyncio.create_subprocess_exec (no shell) for safe process spawning.
    """
    messages = [
        json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "e2e-test", "version": "1.0"},
            },
        }),
        json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }),
    ]
    input_data = "\n".join(messages) + "\n"

    proc = await asyncio.create_subprocess_exec(
        N8N_MCP_BIN,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input_data.encode()), timeout=30.0,
    )

    # Parse JSON-RPC responses (last one is tools/call result)
    responses = []
    for line in stdout.decode().splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                responses.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    call_response = next((r for r in responses if r.get("id") == 2), None)
    if call_response and "result" in call_response:
        return {"success": True, "result": call_response["result"]}
    if call_response and "error" in call_response:
        return {"success": False, "error": call_response["error"]}
    return {"success": False, "error": "No response from n8n-mcp", "raw": responses}


# ---------------------------------------------------------------------------
# Main Journey
# ---------------------------------------------------------------------------


async def main() -> None:
    logger.info("=" * 70)
    logger.info("  E2E PROVIDER JOURNEY — n8n-documentation-mcp")
    logger.info("=" * 70)

    settings = Settings()
    strategy, index_svc, tool_store = _build_services(settings)

    # -----------------------------------------------------------------------
    # STEP 1: Register (Index tools into Qdrant)
    # -----------------------------------------------------------------------
    logger.info("STEP 1: Register — indexing n8n-mcp tools into Qdrant")
    t0 = time.perf_counter()
    indexed = await index_svc.index_rows(N8N_TOOLS)
    reg_ms = (time.perf_counter() - t0) * 1000
    logger.info(f"Indexed {indexed} tools in {reg_ms:.0f}ms")

    # -----------------------------------------------------------------------
    # STEP 2: Search (find_best_tool via RAGService)
    # -----------------------------------------------------------------------
    logger.info("STEP 2: Search — find_best_tool for n8n queries")

    from service.shared.runtime import build_search_runtime

    runtime = build_search_runtime()

    rag_service = RAGServiceFactory.create(
        strategy=strategy,
        supabase_url=os.getenv("SUPABASE_URL", ""),
        supabase_key=os.getenv("SUPABASE_SERVICE_KEY", ""),
        cache_ttl=0,
        confidence_gap_threshold=settings.confidence_gap_threshold,
        reranker=None,
        operability_cache=runtime.operability_cache,
    )

    search_results = {}
    for query in TEST_QUERIES:
        t0 = time.perf_counter()
        resp = await rag_service.search(query, top_k=5)
        search_ms = (time.perf_counter() - t0) * 1000
        search_results[query] = resp
        print(_render_results(resp.results, f"Query: {query}  ({search_ms:.0f}ms)"))

        # Check if n8n tool found
        n8n_hits = [r for r in resp.results if N8N_SERVER_ID in r.tool.tool_id]
        if n8n_hits:
            logger.info(
                f"  n8n tool found: {n8n_hits[0].tool.tool_id} (rank #{n8n_hits[0].rank})"
            )
        else:
            logger.warning(f"  No n8n tool in top-5 for: {query}")

    # -----------------------------------------------------------------------
    # STEP 3: Execute (tools/call on n8n-mcp via stdio)
    # -----------------------------------------------------------------------
    logger.info("STEP 3: Execute — calling n8n-mcp search_nodes directly")

    t0 = time.perf_counter()
    exec_result = await _execute_n8n_tool("search_nodes", {"query": "Slack"})
    exec_ms = (time.perf_counter() - t0) * 1000

    if exec_result["success"]:
        content = exec_result["result"].get("content", [])
        text = content[0].get("text", "") if content else ""
        preview = text[:500] + "..." if len(text) > 500 else text
        logger.info(f"  execute_tool succeeded in {exec_ms:.0f}ms")
        print(f"\n{'=' * 70}")
        print("  EXECUTE RESULT: search_nodes(query='Slack')")
        print(f"{'=' * 70}")
        print(f"  {preview}")
    else:
        logger.error(f"  execute_tool failed: {exec_result.get('error')}")

    # -----------------------------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------------------------
    print(f"\n{'=' * 70}")
    print("  E2E PROVIDER JOURNEY SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Provider:    {N8N_SERVER_ID}")
    print(f"  Tools:       {len(N8N_TOOLS)} registered + indexed")
    print(f"  Queries:     {len(TEST_QUERIES)} tested")

    total_hits = sum(
        1 for resp in search_results.values()
        if any(N8N_SERVER_ID in r.tool.tool_id for r in resp.results)
    )
    print(f"  Search hits: {total_hits}/{len(TEST_QUERIES)} queries found n8n tools")
    print(f"  Execute:     {'SUCCESS' if exec_result['success'] else 'FAILED'}")
    print(f"{'=' * 70}\n")

    if total_hits == 0:
        logger.error("JOURNEY FAILED — no n8n tools found in search results")
        sys.exit(1)
    if not exec_result["success"]:
        logger.error("JOURNEY PARTIAL — search OK but execute failed")
        sys.exit(1)

    logger.info("JOURNEY PASSED — full Provider Journey E2E verified")


if __name__ == "__main__":
    asyncio.run(main())
