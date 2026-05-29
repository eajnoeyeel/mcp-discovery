"""Architecture test: REST search and MCP bridge MUST use identical RAGService wiring.

This test parses both handler modules' RAGServiceFactory.create() calls and asserts
that the parameters match. If they drift, this test fails — preventing the parity
bug where bridge returned different rankings than REST search.

See: RALPLAN Phase 1.3 — runtime parity architecture test.
"""

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SEARCH_HANDLER = REPO / "service" / "lambdas" / "search" / "handler.py"
BRIDGE_HANDLER = REPO / "service" / "lambdas" / "bridge" / "handler.py"

# Parameters that MUST match between search and bridge RAGServiceFactory.create() calls.
# If a new kwarg is added to one handler, it must be added to the other.
PARITY_PARAMS = {
    "strategy",
    "supabase_url",
    "supabase_key",
    "cache_ttl",
    "confidence_gap_threshold",
    "reranker",
    "enable_pending_freshness",
    "rerank_candidate_pool_size",
    "pending_freshness_limit",
    "pending_freshness_timeout_ms",
    "operability_cache",
}


def _extract_factory_kwargs(filepath: Path) -> set[str]:
    """Extract keyword argument names from RAGServiceFactory.create() call in a handler."""
    source = filepath.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match RAGServiceFactory.create(...)
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "create"
            and isinstance(func.value, ast.Name)
            and func.value.id == "RAGServiceFactory"
        ):
            return {kw.arg for kw in node.keywords if kw.arg is not None}

    raise AssertionError(f"RAGServiceFactory.create() call not found in {filepath}")


def test_both_handlers_use_build_search_runtime():
    """Both handlers must import from the same shared runtime module."""
    for handler in (SEARCH_HANDLER, BRIDGE_HANDLER):
        source = handler.read_text()
        assert "from service.shared.runtime import build_search_runtime" in source, (
            f"{handler.name} must import build_search_runtime from service.shared.runtime"
        )


def test_rag_service_factory_kwargs_match():
    """Search and bridge handlers must pass identical kwargs to RAGServiceFactory.create()."""
    search_kwargs = _extract_factory_kwargs(SEARCH_HANDLER)
    bridge_kwargs = _extract_factory_kwargs(BRIDGE_HANDLER)

    only_in_search = search_kwargs - bridge_kwargs
    only_in_bridge = bridge_kwargs - search_kwargs

    assert not only_in_search, f"search handler passes kwargs missing from bridge: {only_in_search}"
    assert not only_in_bridge, f"bridge handler passes kwargs missing from search: {only_in_bridge}"


def test_parity_params_present_in_both():
    """Both handlers must include ALL mandatory parity parameters."""
    search_kwargs = _extract_factory_kwargs(SEARCH_HANDLER)
    bridge_kwargs = _extract_factory_kwargs(BRIDGE_HANDLER)

    missing_search = PARITY_PARAMS - search_kwargs
    missing_bridge = PARITY_PARAMS - bridge_kwargs

    assert not missing_search, f"search handler missing required parity params: {missing_search}"
    assert not missing_bridge, f"bridge handler missing required parity params: {missing_bridge}"


def test_operability_cache_not_none():
    """Both handlers must pass operability_cache (not omit it, which defaults to None)."""
    for handler in (SEARCH_HANDLER, BRIDGE_HANDLER):
        source = handler.read_text()
        assert "operability_cache=runtime.operability_cache" in source, (
            f"{handler.name} must pass operability_cache=runtime.operability_cache"
        )


def test_both_handlers_have_query_logger():
    """Both handlers must have QueryLogger for observability parity.

    Logging dispatch diverges intentionally:
      * search handler fires-and-forgets via ``asyncio.create_task`` +
        ``_pending_tasks`` for GC safety — it does not need the inserted
        query_log row id.
      * bridge handler ``await``s ``log_query`` so it can surface the
        inserted ``query_log_id`` in the ``find_best_tool`` response.
        This correlation key flows back in on ``execute_tool`` and lands
        on ``execution_logs.query_log_id`` (migration 022 funnel).
    """
    search_source = SEARCH_HANDLER.read_text()
    bridge_source = BRIDGE_HANDLER.read_text()

    for name, source in (("search", search_source), ("bridge", bridge_source)):
        assert "QueryLogger" in source, f"{name} handler must import and use QueryLogger"
        assert "log_query" in source, f"{name} handler must invoke log_query"

    # Search keeps fire-and-forget; bridge now awaits for query_log_id.
    assert "_pending_tasks" in search_source, (
        "search handler must retain _pending_tasks (fire-and-forget GC safety)"
    )
    assert "await" in bridge_source and "log_query" in bridge_source, (
        "bridge handler must await log_query to capture query_log_id"
    )
