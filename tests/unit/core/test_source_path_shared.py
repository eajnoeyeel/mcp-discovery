from mcp_discovery.models.core import (
    FindBestToolResponse,
    ScoreBreakdown,
    SearchResult,
    SourcePathLiteral,
)


def test_source_path_literal_exports_six_values():
    import typing

    args = typing.get_args(SourcePathLiteral)
    assert set(args) == {
        "semantic",
        "hybrid_semantic",
        "dense_only_degraded",
        "lexical_fallback",
        "mixed",
        "freshness",
    }


def test_search_result_accepts_hybrid_semantic():
    sr = SearchResult.model_validate(
        {
            "tool": {"tool_id": "s::t", "server_id": "s", "tool_name": "t", "description": "d"},
            "score": 0.5,
            "rank": 1,
            "source_path": "hybrid_semantic",
        }
    )
    assert sr.source_path == "hybrid_semantic"


def test_find_best_tool_response_accepts_freshness():
    r = FindBestToolResponse.model_validate(
        {
            "query": "test query",
            "results": [],
            "confidence": 0.0,
            "disambiguation_needed": False,
            "strategy_used": "flat",
            "latency_ms": 0.0,
            "source_path": "freshness",
        }
    )
    assert r.source_path == "freshness"


def test_score_breakdown_new_fields_default_none():
    sb = ScoreBreakdown(relevance=0.9)
    assert sb.dense_score is None
    assert sb.sparse_score is None
    assert sb.rrf_score is None


def test_score_breakdown_rrf_score_population():
    sb = ScoreBreakdown(relevance=0.55, rrf_score=0.0163, dense_score=0.42, sparse_score=0.38)
    assert sb.rrf_score == 0.0163
    assert sb.dense_score == 0.42
    assert sb.sparse_score == 0.38
