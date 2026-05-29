"""Unit tests for the evaluation harness (src/evaluation/harness.py).

Covers DefaultEvaluator.evaluate() and the module-level evaluate() convenience
function.  All external I/O (strategy.search) is mocked via AsyncMock.
These tests live in tests/unit/ so they are included in the unit coverage report.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from mcp_discovery.evaluation.evaluator import Evaluator
from mcp_discovery.evaluation.harness import DefaultEvaluator, evaluate
from mcp_discovery.evaluation.metrics import EvalResult
from mcp_discovery.models import GroundTruthEntry, MCPTool, SearchResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(tool_id: str) -> MCPTool:
    server_id, tool_name = tool_id.split("::", 1)
    return MCPTool(
        tool_id=tool_id,
        server_id=server_id,
        tool_name=tool_name,
        description=f"Description for {tool_name}",
    )


def _make_result(tool_id: str, score: float, rank: int) -> SearchResult:
    return SearchResult(tool=_make_tool(tool_id), score=score, rank=rank)


def _make_entry(
    query_id: str = "gt-unit-001",
    correct_tool_id: str = "srv1::tool_a",
    query: str = "find tool a",
    correct_server_id: str | None = None,
) -> GroundTruthEntry:
    sid = correct_server_id or correct_tool_id.split("::")[0]
    return GroundTruthEntry(
        query_id=query_id,
        query=query,
        correct_server_id=sid,
        correct_tool_id=correct_tool_id,
        difficulty="easy",
        category="general",
        ambiguity="low",
        source="manual_seed",
        manually_verified=True,
        author="test",
        created_at="2026-04-15",
        alternative_tools=None,
    )


# ---------------------------------------------------------------------------
# DefaultEvaluator — class contract
# ---------------------------------------------------------------------------


class TestDefaultEvaluatorContract:
    def test_is_evaluator_subclass(self):
        assert issubclass(DefaultEvaluator, Evaluator)

    def test_default_gap_threshold_is_0_15(self):
        ev = DefaultEvaluator()
        assert ev._gap_threshold == pytest.approx(0.15)

    def test_custom_gap_threshold_stored(self):
        ev = DefaultEvaluator(gap_threshold=0.25)
        assert ev._gap_threshold == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# DefaultEvaluator.evaluate — happy-path results
# ---------------------------------------------------------------------------


class TestDefaultEvaluatorEvaluate:
    async def test_returns_eval_result_instance(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[_make_result("srv1::tool_a", 0.9, 1)])
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert isinstance(result, EvalResult)

    async def test_n_queries_matches_input_length(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        entries = [_make_entry(f"gt-{i:03d}") for i in range(4)]
        result = await DefaultEvaluator().evaluate(strategy, entries, top_k=5)
        assert result.n_queries == 4

    async def test_k_used_matches_top_k_argument(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=7)
        assert result.k_used == 7

    async def test_n_failed_zero_when_no_exceptions(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert result.n_failed == 0

    async def test_strategy_called_once_per_query(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        entries = [_make_entry(f"gt-{i:03d}") for i in range(5)]
        await DefaultEvaluator().evaluate(strategy, entries, top_k=10)
        assert strategy.search.call_count == 5

    async def test_strategy_called_with_entry_query_and_top_k(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        entry = _make_entry(query="list github repos", correct_tool_id="srv::t")
        await DefaultEvaluator().evaluate(strategy, [entry], top_k=5)
        strategy.search.assert_called_once_with("list github repos", top_k=5)

    async def test_precision_at_1_correct_when_top_1_matches(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(
            return_value=[
                _make_result("srv1::tool_a", 0.9, 1),
                _make_result("srv1::tool_b", 0.5, 2),
            ]
        )
        result = await DefaultEvaluator().evaluate(
            strategy, [_make_entry(correct_tool_id="srv1::tool_a")], top_k=10
        )
        assert result.precision_at_1 == pytest.approx(1.0)

    async def test_precision_at_1_zero_when_top_1_wrong(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(
            return_value=[
                _make_result("srv1::tool_b", 0.9, 1),
                _make_result("srv1::tool_a", 0.5, 2),
            ]
        )
        result = await DefaultEvaluator().evaluate(
            strategy, [_make_entry(correct_tool_id="srv1::tool_a")], top_k=10
        )
        assert result.precision_at_1 == pytest.approx(0.0)

    async def test_recall_at_k_one_when_correct_in_results(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(
            return_value=[
                _make_result("srv1::tool_b", 0.9, 1),
                _make_result("srv1::tool_a", 0.5, 2),
            ]
        )
        result = await DefaultEvaluator().evaluate(
            strategy, [_make_entry(correct_tool_id="srv1::tool_a")], top_k=10
        )
        assert result.recall_at_k == pytest.approx(1.0)

    async def test_mrr_at_rank_2_returns_half(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(
            return_value=[
                _make_result("srv1::tool_b", 0.9, 1),
                _make_result("srv1::tool_a", 0.5, 2),
            ]
        )
        result = await DefaultEvaluator().evaluate(
            strategy, [_make_entry(correct_tool_id="srv1::tool_a")], top_k=10
        )
        assert result.mrr == pytest.approx(0.5)

    async def test_per_query_length_equals_number_of_entries(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[_make_result("srv1::tool_a", 0.9, 1)])
        entries = [_make_entry(f"gt-{i:03d}") for i in range(3)]
        result = await DefaultEvaluator().evaluate(strategy, entries, top_k=10)
        assert len(result.per_query) == 3

    async def test_per_query_tuple_not_list(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert isinstance(result.per_query, tuple)

    async def test_latency_stats_non_negative(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert result.latency_p50 >= 0.0
        assert result.latency_p95 >= 0.0
        assert result.latency_p99 >= 0.0
        assert result.latency_mean >= 0.0

    async def test_per_query_latency_ms_non_negative(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert result.per_query[0].latency_ms >= 0.0

    async def test_server_recall_computed(self):
        strategy = AsyncMock()
        # result has same server_id as entry's correct_server_id
        strategy.search = AsyncMock(return_value=[_make_result("srv1::tool_a", 0.9, 1)])
        result = await DefaultEvaluator().evaluate(
            strategy, [_make_entry(correct_tool_id="srv1::tool_a")], top_k=10
        )
        assert result.server_recall_at_k == pytest.approx(1.0)

    async def test_rank_of_correct_set_for_found_tool(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(
            return_value=[
                _make_result("srv1::tool_b", 0.9, 1),
                _make_result("srv1::tool_a", 0.6, 2),
            ]
        )
        result = await DefaultEvaluator().evaluate(
            strategy, [_make_entry(correct_tool_id="srv1::tool_a")], top_k=10
        )
        assert result.per_query[0].rank_of_correct == 2

    async def test_rank_of_correct_none_when_tool_not_in_results(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[_make_result("srv1::tool_b", 0.9, 1)])
        result = await DefaultEvaluator().evaluate(
            strategy, [_make_entry(correct_tool_id="srv1::tool_a")], top_k=10
        )
        assert result.per_query[0].rank_of_correct is None

    async def test_retrieved_tool_ids_contains_all_result_ids(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(
            return_value=[
                _make_result("srv1::tool_a", 0.9, 1),
                _make_result("srv1::tool_b", 0.5, 2),
            ]
        )
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert result.per_query[0].retrieved_tool_ids == ("srv1::tool_a", "srv1::tool_b")


# ---------------------------------------------------------------------------
# DefaultEvaluator.evaluate — empty input
# ---------------------------------------------------------------------------


class TestDefaultEvaluatorEmptyInput:
    async def test_empty_queries_returns_zero_metrics(self):
        strategy = AsyncMock()
        result = await DefaultEvaluator().evaluate(strategy, [], top_k=10)
        assert result.n_queries == 0
        assert result.n_failed == 0
        assert result.precision_at_1 == pytest.approx(0.0)
        assert result.recall_at_k == pytest.approx(0.0)
        assert result.mrr == pytest.approx(0.0)
        assert result.ndcg_at_5 == pytest.approx(0.0)

    async def test_empty_queries_per_query_is_empty_tuple(self):
        strategy = AsyncMock()
        result = await DefaultEvaluator().evaluate(strategy, [], top_k=10)
        assert result.per_query == ()

    async def test_empty_queries_strategy_never_called(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        await DefaultEvaluator().evaluate(strategy, [], top_k=10)
        strategy.search.assert_not_called()

    async def test_empty_queries_confusion_rate_is_none(self):
        strategy = AsyncMock()
        result = await DefaultEvaluator().evaluate(strategy, [], top_k=10)
        assert result.confusion_rate is None


# ---------------------------------------------------------------------------
# DefaultEvaluator.evaluate — strategy name resolution
# ---------------------------------------------------------------------------


class TestStrategyNameResolution:
    async def test_uses_name_attribute_when_string(self):
        strategy = AsyncMock()
        strategy.name = "custom_flat"
        strategy.search = AsyncMock(return_value=[])
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert result.strategy_name == "custom_flat"

    async def test_falls_back_to_class_name_when_no_name_attribute(self):
        strategy = AsyncMock()
        # Remove any accidental name attribute so class name fallback is triggered
        if hasattr(strategy, "name"):
            del strategy.name
        strategy.search = AsyncMock(return_value=[])
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert result.strategy_name == type(strategy).__name__

    async def test_falls_back_to_class_name_when_name_attribute_not_string(self):
        strategy = AsyncMock()
        strategy.name = 42  # non-string name attribute
        strategy.search = AsyncMock(return_value=[])
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert result.strategy_name == type(strategy).__name__


# ---------------------------------------------------------------------------
# DefaultEvaluator.evaluate — exception isolation
# ---------------------------------------------------------------------------


class TestExceptionIsolation:
    async def test_failed_query_increments_n_failed(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(side_effect=RuntimeError("timeout"))
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert result.n_failed == 1

    async def test_failed_query_included_in_per_query_as_zero_result(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(side_effect=RuntimeError("timeout"))
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert len(result.per_query) == 1
        assert result.per_query[0].top_1_correct is False
        assert result.per_query[0].in_top_k is False
        assert result.per_query[0].retrieved_tool_ids == ()
        assert result.per_query[0].confidence == pytest.approx(0.0)
        assert result.per_query[0].rank_of_correct is None

    async def test_failed_query_counted_in_denominator(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(side_effect=RuntimeError("timeout"))
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert result.n_queries == 1
        assert result.precision_at_1 == pytest.approx(0.0)

    async def test_partial_failure_dilutes_precision(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(
            side_effect=[
                RuntimeError("timeout"),
                [_make_result("srv1::tool_a", 0.9, 1)],
            ]
        )
        entries = [_make_entry("gt-001"), _make_entry("gt-002")]
        result = await DefaultEvaluator().evaluate(strategy, entries, top_k=10)
        assert result.n_queries == 2
        assert result.n_failed == 1
        # P@1 = 1/2 (failed counts as incorrect)
        assert result.precision_at_1 == pytest.approx(0.5)

    async def test_failed_query_latency_included_in_aggregate(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(
            side_effect=[
                RuntimeError("timeout"),
                [_make_result("srv1::tool_a", 0.9, 1)],
            ]
        )
        entries = [_make_entry("gt-001"), _make_entry("gt-002")]
        evaluator = DefaultEvaluator()

        perf_patch = "mcp_discovery.evaluation.harness.time.perf_counter"
        with patch(perf_patch, side_effect=[0.0, 0.2, 1.0, 1.1]):
            result = await evaluator.evaluate(strategy, entries, top_k=10)

        assert result.n_failed == 1
        assert result.latency_mean == pytest.approx(150.0)
        assert result.per_query[0].latency_ms == pytest.approx(200.0)

    async def test_all_queries_fail_all_metrics_zero(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(side_effect=ValueError("all broken"))
        entries = [_make_entry(f"gt-{i:03d}") for i in range(3)]
        result = await DefaultEvaluator().evaluate(strategy, entries, top_k=10)
        assert result.n_queries == 3
        assert result.n_failed == 3
        assert result.precision_at_1 == pytest.approx(0.0)
        assert result.recall_at_k == pytest.approx(0.0)
        assert result.mrr == pytest.approx(0.0)

    async def test_exception_does_not_propagate_to_caller(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(side_effect=RuntimeError("crash"))
        # Must not raise — exceptions are swallowed per-query
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert isinstance(result, EvalResult)


# ---------------------------------------------------------------------------
# Module-level evaluate() convenience function
# ---------------------------------------------------------------------------


class TestModuleLevelEvaluate:
    async def test_returns_eval_result(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[_make_result("srv1::tool_a", 0.9, 1)])
        result = await evaluate(strategy, [_make_entry()], top_k=10)
        assert isinstance(result, EvalResult)

    async def test_delegates_to_default_evaluator(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        result = await evaluate(strategy, [_make_entry()], top_k=10)
        assert result.n_queries == 1

    async def test_accepts_custom_gap_threshold(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[_make_result("srv1::tool_a", 0.9, 1)])
        # Should not raise regardless of threshold value
        result = await evaluate(strategy, [_make_entry()], top_k=10, gap_threshold=0.30)
        assert isinstance(result, EvalResult)

    async def test_default_top_k_is_10(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        result = await evaluate(strategy, [_make_entry()])
        assert result.k_used == 10

    async def test_empty_queries_returns_zero_metrics(self):
        strategy = AsyncMock()
        result = await evaluate(strategy, [], top_k=5)
        assert result.n_queries == 0
        assert result.precision_at_1 == pytest.approx(0.0)

    async def test_multiple_queries_all_correct(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[_make_result("srv1::tool_a", 0.9, 1)])
        entries = [_make_entry(f"gt-{i:03d}") for i in range(3)]
        result = await evaluate(strategy, entries, top_k=10)
        assert result.n_queries == 3
        assert result.precision_at_1 == pytest.approx(1.0)

    async def test_strategy_receives_correct_query_text(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        entry = _make_entry(query="create github issue", correct_tool_id="srv::t")
        await evaluate(strategy, [entry], top_k=3)
        strategy.search.assert_called_once_with("create github issue", top_k=3)


# ---------------------------------------------------------------------------
# Edge cases: confidence and ndcg accumulation
# ---------------------------------------------------------------------------


class TestConfidenceAndNDCGAccumulation:
    async def test_ndcg_at_5_zero_when_results_empty(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[])
        result = await DefaultEvaluator().evaluate(strategy, [_make_entry()], top_k=10)
        assert result.ndcg_at_5 == pytest.approx(0.0)

    async def test_ndcg_at_5_positive_when_correct_at_rank_1(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[_make_result("srv1::tool_a", 0.9, 1)])
        result = await DefaultEvaluator().evaluate(
            strategy, [_make_entry(correct_tool_id="srv1::tool_a")], top_k=10
        )
        assert result.ndcg_at_5 > 0.0

    async def test_ndcg_at_5_averaged_across_queries(self):
        strategy = AsyncMock()
        # First query: correct at rank 1 → NDCG=1.0
        # Second query: no results → NDCG=0.0
        strategy.search = AsyncMock(
            side_effect=[
                [_make_result("srv1::tool_a", 0.9, 1)],
                [],
            ]
        )
        entries = [
            _make_entry("gt-001", correct_tool_id="srv1::tool_a"),
            _make_entry("gt-002", correct_tool_id="srv1::tool_a"),
        ]
        result = await DefaultEvaluator().evaluate(strategy, entries, top_k=10)
        # ndcg_at_5 = (1.0 + 0.0) / 2 = 0.5
        assert result.ndcg_at_5 == pytest.approx(0.5)

    async def test_correct_server_in_top_k_true_when_server_matches(self):
        strategy = AsyncMock()
        # Result has server_id="srv1", entry has correct_server_id="srv1"
        strategy.search = AsyncMock(return_value=[_make_result("srv1::other_tool", 0.9, 1)])
        result = await DefaultEvaluator().evaluate(
            strategy, [_make_entry(correct_tool_id="srv1::tool_a")], top_k=10
        )
        # Server found even though tool_id is wrong
        assert result.per_query[0].correct_server_in_top_k is True

    async def test_correct_server_in_top_k_false_when_server_absent(self):
        strategy = AsyncMock()
        strategy.search = AsyncMock(return_value=[_make_result("other_srv::tool_x", 0.9, 1)])
        result = await DefaultEvaluator().evaluate(
            strategy, [_make_entry(correct_tool_id="srv1::tool_a")], top_k=10
        )
        assert result.per_query[0].correct_server_in_top_k is False
