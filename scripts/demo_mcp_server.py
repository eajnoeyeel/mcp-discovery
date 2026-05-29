"""Demo MCP server for MCP Discovery Platform — E4v2 experiment comparison.

Exposes find_best_tool via stdio MCP so Claude Code can call it directly.

Two modes:
1. Live mode (default): ParallelStrategy + Qdrant search + optional enriched injection
2. Cluster mode (cluster=<name>): E4v2 fixed-candidate evaluation — bypasses Qdrant,
   uses pre-defined cluster tools directly as Cohere candidates. Faithful to E4v2 design.

E4v2 design: Offline Fixed-Candidate Evaluation
- Embedding search is bypassed; fixed cluster tools are fed directly to Cohere reranker
- Only the description fed to Cohere reranker changes:
  - use_enriched=False: reranker sees tool.description (original)
  - use_enriched=True:  reranker sees tool.selection_description (enriched, injected)

CTO demo:
  find_best_tool(query="Search for records in the Sales Expenses table",
                 cluster="database_records", use_enriched=false)
  → airtable::search_records ranks low (original: "Search for records containing specific text")

  find_best_tool(query="Search for records in the Sales Expenses table",
                 cluster="database_records", use_enriched=true)
  → airtable::search_records ranks #1 (enriched: "Searches for records in a specified table...")

Clusters: file_operations | git_vcs | database_records

Registration: see .mcp.json at project root.
Run: uv run python scripts/demo_mcp_server.py
"""

# ruff: noqa: E402

import asyncio
import json
import os
import sys
from pathlib import Path

# --- Path bootstrap (before all project imports) ---
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_SRC = str(_ROOT / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from loguru import logger  # noqa: E402
from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
from mcp.types import TextContent, Tool  # noqa: E402
from qdrant_client import AsyncQdrantClient  # noqa: E402

from mcp_discovery.config import Settings  # noqa: E402
from mcp_discovery.embedding.openai_embedder import OpenAIEmbedder  # noqa: E402
from mcp_discovery.models import SearchResult  # noqa: E402
from mcp_discovery.pipeline.flat import FlatStrategy  # noqa: E402
from mcp_discovery.reranking.cohere_reranker import CohereReranker  # noqa: E402
from mcp_discovery.retrieval.qdrant_store import QdrantStore  # noqa: E402

TOOL_COLLECTION = "mcp_tools"
CLUSTERS_PATH = _ROOT / "data" / "e4v2" / "clusters.json"

# Loaded at startup
_ENRICHED_DESCRIPTIONS: dict[str, str] = {}  # tool_id -> enriched_description
_CLUSTERS: dict[str, list[dict]] = {}  # cluster_name -> list of tool dicts

# FlatStrategy: embedding → rerank, no server-level filtering.
# use_enriched path: _STRATEGY_NO_RERANK (embedding only) → inject → _RERANKER
# use_enriched=False: _STRATEGY (embedding + rerank with original descriptions)
_STRATEGY: FlatStrategy | None = None
_STRATEGY_NO_RERANK: FlatStrategy | None = None
_RERANKER: CohereReranker | None = None

server = Server("mcp-discovery-demo")

FIND_BEST_TOOL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Natural language description of what you want to do",
        },
        "top_k": {
            "type": "integer",
            "description": "Number of results to return",
            "default": 6,
            "minimum": 1,
            "maximum": 10,
        },
        "use_enriched": {
            "type": "boolean",
            "description": (
                "If true, inject E4v2 enriched descriptions into candidates before reranking. "
                "Default false = original descriptions."
            ),
            "default": False,
        },
        "cluster": {
            "type": "string",
            "description": (
                "E4v2 cluster mode: bypass Qdrant and use fixed cluster candidates directly. "
                "Options: 'file_operations', 'git_vcs', 'database_records'. "
                "Best for CTO demo — faithful to E4v2 offline evaluation design."
            ),
        },
    },
    "required": ["query"],
}


def _load_clusters_data(
    path: Path,
) -> tuple[dict[str, str], dict[str, list[dict]]]:
    """Load E4v2 clusters.json.

    Args:
        path: Path to clusters.json.

    Returns:
        Tuple of:
        - enriched_descriptions: tool_id -> enriched_description (all clusters)
        - clusters: cluster_name -> list of tool dicts (tool_id, descriptions)
    """
    with path.open() as f:
        data = json.load(f)
    enriched: dict[str, str] = {}
    clusters: dict[str, list[dict]] = {}
    for cluster in data["clusters"]:
        name = cluster["name"]
        clusters[name] = cluster["tools"]
        for tool in cluster["tools"]:
            enriched[tool["tool_id"]] = tool["enriched_description"]
    return enriched, clusters


def _build_cluster_candidates(
    cluster_tools: list[dict],
    *,
    use_enriched: bool,
) -> list[SearchResult]:
    """Build fixed SearchResult candidates from E4v2 cluster tools.

    Mirrors the offline fixed-candidate design of E4v2: candidates are pre-defined,
    not retrieved from Qdrant. The description fed to Cohere is controlled by use_enriched.

    Args:
        cluster_tools: List of tool dicts from clusters.json.
        use_enriched: If True, set selection_description to enriched_description.

    Returns:
        SearchResult list with uniform score=1.0 (pre-rerank).
    """
    from mcp_discovery.models import MCPTool

    results = []
    for i, t in enumerate(cluster_tools):
        tool_id: str = t["tool_id"]
        parts = tool_id.split("::", 1)
        server_id = parts[0]
        tool_name = parts[1] if len(parts) > 1 else tool_id
        orig_desc: str = t["original_description"]
        enr_desc: str = t["enriched_description"]
        tool = MCPTool(
            server_id=server_id,
            tool_name=tool_name,
            tool_id=tool_id,
            description=orig_desc,
            selection_description=enr_desc if use_enriched else None,
        )
        results.append(SearchResult(tool=tool, score=1.0, rank=i + 1))
    return results


def _inject_selection_descriptions(
    results: list[SearchResult],
    enriched: dict[str, str],
) -> list[SearchResult]:
    """Return new SearchResult list with selection_description injected for known tools.

    Creates new MCPTool instances (immutable pattern) rather than mutating in place.

    Args:
        results: Candidates from embedding search.
        enriched: Mapping of tool_id -> enriched_description.

    Returns:
        New list where matching tools have selection_description set.
    """
    injected = []
    for r in results:
        tool = r.tool
        enr_desc = enriched.get(tool.tool_id)
        if enr_desc is not None:
            tool = tool.model_copy(update={"selection_description": enr_desc})
        injected.append(r.model_copy(update={"tool": tool}))
    return injected


def _format_results(results: list[SearchResult], *, use_enriched: bool) -> str:
    """Render search results as markdown for CTO demo.

    Shows the description the reranker actually used:
    - use_enriched=False: shows tool.description (original)
    - use_enriched=True:  shows tool.selection_description (enriched)

    Args:
        results: Ordered (reranked) list of SearchResult objects.
        use_enriched: Controls label and which description field to display.

    Returns:
        Markdown-formatted string with rank, tool_id, score, description.
    """
    label = "enriched (E4v2)" if use_enriched else "original"
    if not results:
        return f"## Results ({label})\n\nNo results found."

    lines = [f"## Results ({label})\n"]
    for r in results:
        if use_enriched and r.tool.selection_description:
            desc = r.tool.selection_description
        else:
            desc = r.tool.description or "_no description_"
        lines.append(f"**#{r.rank}** `{r.tool.tool_id}` — score: `{r.score:.4f}`\n> {desc}\n")
    return "\n".join(lines)


async def _run_search(
    query: str,
    *,
    top_k: int = 6,
    use_enriched: bool = False,
    cluster: str | None = None,
) -> list[SearchResult]:
    """Run search — cluster mode (E4v2 fixed-candidate) or live Qdrant mode.

    Cluster mode (cluster=<name>):
        Bypasses Qdrant. Uses pre-defined cluster tools as Cohere candidates.
        Faithful to E4v2 offline fixed-candidate design.
        use_enriched controls whether selection_description (enriched) is set.

    Live mode (cluster=None):
        use_enriched=False: full pipeline (_STRATEGY) — Cohere sees tool.description
        use_enriched=True:  embedding-only → inject selection_description → rerank

    Args:
        query: Natural language query.
        top_k: Number of final results to return.
        use_enriched: Inject enriched selection_description before reranking.
        cluster: If set, use E4v2 fixed candidates for this cluster.

    Returns:
        Ordered list of SearchResult objects.
    """
    logger.info(
        f"_run_search: cluster={cluster!r}, use_enriched={use_enriched}, query='{query[:60]}'"
    )

    if cluster is not None:
        # --- Cluster mode: E4v2 offline fixed-candidate evaluation ---
        if cluster not in _CLUSTERS:
            available = list(_CLUSTERS.keys())
            raise ValueError(f"Unknown cluster {cluster!r}. Available: {available}")
        if _RERANKER is None:
            raise RuntimeError(
                "Legacy reranker API key required for cluster mode — "
                "reranker is the only stage in E4v2 fixed-candidate evaluation."
            )
        candidates = _build_cluster_candidates(_CLUSTERS[cluster], use_enriched=use_enriched)
        return await _RERANKER.rerank(query, candidates, top_k=min(top_k, len(candidates)))

    # --- Live mode: Qdrant search ---
    if _STRATEGY is None or _STRATEGY_NO_RERANK is None:
        raise RuntimeError(
            "Strategies not initialized — call _init_strategy() before serving requests."
        )
    if use_enriched:
        raw_results = await _STRATEGY_NO_RERANK.search(query, top_k=top_k * 3)
        injected = _inject_selection_descriptions(raw_results, _ENRICHED_DESCRIPTIONS)
        if _RERANKER is not None:
            return await _RERANKER.rerank(query, injected, top_k=top_k)
        return injected[:top_k]
    else:
        return await _STRATEGY.search(query, top_k=top_k)


async def _handle_find_best_tool(arguments: dict) -> list[TextContent]:
    """Handle a find_best_tool MCP tool call.

    Args:
        arguments: Dict with 'query', optional 'top_k', optional 'use_enriched', optional 'cluster'.

    Returns:
        Single-element list with TextContent containing markdown results.
    """
    query: str = arguments["query"]
    top_k: int = int(arguments.get("top_k", 6))
    use_enriched: bool = bool(arguments.get("use_enriched", False))
    cluster: str | None = arguments.get("cluster") or None
    results = await _run_search(query, top_k=top_k, use_enriched=use_enriched, cluster=cluster)
    return [TextContent(type="text", text=_format_results(results, use_enriched=use_enriched))]


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(
            name="find_best_tool",
            description=(
                "Search for the best MCP tool for a given task. "
                "Set use_enriched=true to use E4v2 enriched descriptions for reranking "
                "(same embedding search, different description fed to the legacy reranker)."
            ),
            inputSchema=FIND_BEST_TOOL_SCHEMA,
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "find_best_tool":
        return await _handle_find_best_tool(arguments)
    raise ValueError(f"Unknown tool: {name!r}")


def _init_strategy() -> None:
    """Build two FlatStrategy instances sharing one client/embedder/tool_store.

    FlatStrategy: embedding → rerank, no server-level filtering.
    This avoids RRF-induced rank distortion from server layer.

    _STRATEGY           — with reranker: for use_enriched=False
    _STRATEGY_NO_RERANK — without reranker: embedding-only for use_enriched=True path
    _RERANKER           — standalone: reranks after selection_description injection
    """
    global _STRATEGY, _STRATEGY_NO_RERANK, _RERANKER, _ENRICHED_DESCRIPTIONS, _CLUSTERS

    if not CLUSTERS_PATH.exists():
        raise FileNotFoundError(
            f"E4v2 clusters not found at {CLUSTERS_PATH}. Run scripts/run_e4v2.py first."
        )
    _ENRICHED_DESCRIPTIONS, _CLUSTERS = _load_clusters_data(CLUSTERS_PATH)

    settings = Settings()

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required. Set it in .env or environment.")

    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimension=settings.embedding_dimension,
    )

    legacy_rerank_api_key = os.getenv("COHERE_API_KEY")
    if legacy_rerank_api_key:
        try:
            _RERANKER = CohereReranker(
                api_key=legacy_rerank_api_key,
                model=os.getenv("RERANK_MODEL", "rerank-v3.5"),
            )
        except RuntimeError as exc:
            logger.warning(f"Legacy reranker unavailable; reranker disabled: {exc}")
    else:
        logger.warning(
            "Legacy reranker API key not set — reranker disabled. "
            "E4v2 demo requires the historical reranker path to show description impact."
        )

    tool_store = QdrantStore(client=client, collection_name=TOOL_COLLECTION)

    _STRATEGY = FlatStrategy(embedder=embedder, tool_store=tool_store, reranker=_RERANKER)
    _STRATEGY_NO_RERANK = FlatStrategy(
        embedder=embedder,
        tool_store=tool_store,
        reranker=None,  # intentional: reranking done separately after description injection
    )

    reranker_status = "enabled" if _RERANKER else "DISABLED (no legacy reranker key)"
    cluster_names = list(_CLUSTERS.keys())
    logger.info(
        f"Strategies ready: collection='{TOOL_COLLECTION}', "
        f"enriched_tools={len(_ENRICHED_DESCRIPTIONS)}, "
        f"clusters={cluster_names}, reranker={reranker_status}"
    )
    print(
        f"[mcp-discovery-demo] Ready. "
        f"collection={TOOL_COLLECTION}, "
        f"clusters={cluster_names}, reranker={reranker_status}",
        file=sys.stderr,
    )


async def main() -> None:
    _init_strategy()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
