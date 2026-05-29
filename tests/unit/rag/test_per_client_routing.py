from mcp_discovery.models.core import MCPTool, SearchResult
from service.rag.service import RAGService, _apply_selection_descriptions


def make_result(
    tool_id: str, description: str, selection_description: str | None = None
) -> SearchResult:
    server_id, tool_name = tool_id.split("::")
    tool = MCPTool(
        tool_id=tool_id,
        server_id=server_id,
        tool_name=tool_name,
        description=description,
        selection_description=selection_description,
    )
    return SearchResult(tool=tool, score=0.9, rank=1, reason="test")


VARIANT_MAP = {
    "server::tool_a": {
        "openai": "GPT-optimized desc",
        "anthropic": "Claude-optimized desc",
    },
}


class TestApplySelectionDescriptions:
    def test_gpt_variant_applied(self):
        results = [make_result("server::tool_a", "original", "selection")]
        out = _apply_selection_descriptions(results, "openai", VARIANT_MAP)
        assert out[0].tool.description == "GPT-optimized desc"

    def test_claude_variant_applied(self):
        results = [make_result("server::tool_a", "original", "selection")]
        out = _apply_selection_descriptions(results, "anthropic", VARIANT_MAP)
        assert out[0].tool.description == "Claude-optimized desc"

    def test_gemini_skips_routing_uses_selection(self):
        results = [make_result("server::tool_a", "original", "selection")]
        out = _apply_selection_descriptions(results, "gemini-flash", VARIANT_MAP)
        assert out[0].tool.description == "selection"

    def test_gemini_prefix_any_variant_uses_selection(self):
        results = [make_result("server::tool_a", "original", "selection")]
        out = _apply_selection_descriptions(results, "gemini-pro", VARIANT_MAP)
        assert out[0].tool.description == "selection"

    def test_unknown_client_falls_back_to_selection(self):
        results = [make_result("server::tool_a", "original", "selection")]
        out = _apply_selection_descriptions(results, "unknown-vendor", VARIANT_MAP)
        assert out[0].tool.description == "selection"

    def test_no_client_id_preserves_raw_description(self):
        results = [make_result("server::tool_a", "original", "selection")]
        out = _apply_selection_descriptions(results, None, VARIANT_MAP)
        assert out[0].tool.description == "original"

    def test_no_variant_map_uses_selection(self):
        results = [make_result("server::tool_a", "original", "selection")]
        out = _apply_selection_descriptions(results, "openai", None)
        assert out[0].tool.description == "selection"

    def test_no_selection_description_falls_back_to_raw(self):
        results = [make_result("server::tool_a", "original", None)]
        out = _apply_selection_descriptions(results, "openai", {})
        assert out[0].tool.description == "original"

    def test_tool_not_in_variant_map_falls_back_to_selection(self):
        results = [make_result("server::tool_b", "original", "selection")]
        out = _apply_selection_descriptions(results, "openai", VARIANT_MAP)
        assert out[0].tool.description == "selection"

    def test_result_list_unchanged_when_no_swap_needed(self):
        results = [make_result("server::tool_a", "original", None)]
        out = _apply_selection_descriptions(results, None, None)
        assert out[0] is results[0]

    def test_multiple_results_each_routed_independently(self):
        results = [
            make_result("server::tool_a", "raw_a", "sel_a"),
            make_result("server::tool_b", "raw_b", "sel_b"),
        ]
        out = _apply_selection_descriptions(results, "openai", VARIANT_MAP)
        assert out[0].tool.description == "GPT-optimized desc"
        assert out[1].tool.description == "sel_b"

    def test_empty_results_returns_empty(self):
        out = _apply_selection_descriptions([], "openai", VARIANT_MAP)
        assert out == []


class TestCacheKeyIsolation:
    def test_different_client_ids_produce_different_keys(self):
        k1 = RAGService._cache_key("query", 3, True, "openai")
        k2 = RAGService._cache_key("query", 3, True, "anthropic")
        assert k1 != k2

    def test_none_client_id_is_backward_compatible(self):
        k_none = RAGService._cache_key("query", 3, True, None)
        k_no_arg = RAGService._cache_key("query", 3, True)
        assert k_none == k_no_arg

    def test_client_id_does_not_affect_different_queries(self):
        k1 = RAGService._cache_key("q1", 3, True, "openai")
        k2 = RAGService._cache_key("q2", 3, True, "openai")
        assert k1 != k2

    def test_client_id_included_in_key_when_provided(self):
        k_with = RAGService._cache_key("query", 3, True, "openai")
        k_without = RAGService._cache_key("query", 3, True)
        assert k_with != k_without

    def test_same_params_same_key(self):
        k1 = RAGService._cache_key("query", 5, False, "anthropic")
        k2 = RAGService._cache_key("query", 5, False, "anthropic")
        assert k1 == k2

    def test_freshness_flag_affects_key(self):
        k1 = RAGService._cache_key("query", 3, True, "openai")
        k2 = RAGService._cache_key("query", 3, False, "openai")
        assert k1 != k2

    def test_top_k_affects_key(self):
        k1 = RAGService._cache_key("query", 3, True, "openai")
        k2 = RAGService._cache_key("query", 5, True, "openai")
        assert k1 != k2
