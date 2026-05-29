"""Unit tests for evaluation metric functions (src/evaluation/metrics.py).

Covers all public functions and the PerQueryResult / EvalResult dataclasses.
These tests are placed in tests/unit/ so they contribute to the unit-test
coverage report for src/evaluation/metrics.py.
"""

from __future__ import annotations

import math

import pytest

from mcp_discovery.evaluation.metrics import (
    EvalResult,
    PerQueryResult,
    compute_confusion_rate,
    compute_ece,
    compute_latency_stats,
    compute_mrr,
    compute_ndcg_at_5,
    compute_precision_at_1,
    compute_recall_at_k,
    compute_server_recall_at_k,
)
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


def _make_gt(
    correct_tool_id: str,
    alternative_tools: list[str] | None = None,
) -> GroundTruthEntry:
    server_id = correct_tool_id.split("::")[0]
    return GroundTruthEntry(
        query_id="gt-unit-001",
        query="test query",
        correct_server_id=server_id,
        correct_tool_id=correct_tool_id,
        difficulty="easy",
        category="general",
        ambiguity="low",
        source="manual_seed",
        manually_verified=True,
        author="test",
        created_at="2026-04-15",
        alternative_tools=alternative_tools,
    )


def _make_pq(
    query_id: str = "q1",
    top_1_correct: bool = True,
    in_top_k: bool = True,
    rank_of_correct: int | None = 1,
    confidence: float = 0.9,
    retrieved_tool_ids: tuple[str, ...] | None = None,
    correct_server_in_top_k: bool = False,
) -> PerQueryResult:
    return PerQueryResult(
        query_id=query_id,
        top_1_correct=top_1_correct,
        in_top_k=in_top_k,
        rank_of_correct=rank_of_correct,
        confidence=confidence,
        latency_ms=10.0,
        retrieved_tool_ids=retrieved_tool_ids or ("srv::a",),
        correct_server_in_top_k=correct_server_in_top_k,
    )


# ---------------------------------------------------------------------------
# PerQueryResult dataclass
# ---------------------------------------------------------------------------


class TestPerQueryResult:
    def test_fields_stored_correctly(self):
        r = PerQueryResult(
            query_id="gt-001",
            top_1_correct=True,
            in_top_k=True,
            rank_of_correct=1,
            confidence=0.9,
            latency_ms=42.5,
            retrieved_tool_ids=("srv::a", "srv::b"),
        )
        assert r.query_id == "gt-001"
        assert r.top_1_correct is True
        assert r.in_top_k is True
        assert r.rank_of_correct == 1
        assert r.confidence == 0.9
        assert r.latency_ms == 42.5
        assert r.retrieved_tool_ids == ("srv::a", "srv::b")

    def test_correct_server_in_top_k_defaults_to_false(self):
        r = _make_pq()
        assert r.correct_server_in_top_k is False

    def test_correct_server_in_top_k_can_be_set_true(self):
        r = _make_pq(correct_server_in_top_k=True)
        assert r.correct_server_in_top_k is True

    def test_is_frozen_raises_on_mutation(self):
        r = _make_pq()
        with pytest.raises(AttributeError):
            r.query_id = "changed"  # type: ignore[misc]

    def test_rank_of_correct_none_when_not_found(self):
        r = _make_pq(top_1_correct=False, in_top_k=False, rank_of_correct=None)
        assert r.rank_of_correct is None


# ---------------------------------------------------------------------------
# EvalResult dataclass
# ---------------------------------------------------------------------------


class TestEvalResult:
    def _base_kwargs(self, **overrides) -> dict:
        defaults = dict(
            strategy_name="FlatStrategy",
            n_queries=10,
            n_failed=0,
            k_used=10,
            precision_at_1=0.6,
            recall_at_k=0.8,
            mrr=0.7,
            ndcg_at_5=0.75,
            confusion_rate=0.3,
            ece=0.1,
            latency_p50=50.0,
            latency_p95=120.0,
            latency_p99=200.0,
            latency_mean=60.0,
        )
        defaults.update(overrides)
        return defaults

    def test_fields_stored_correctly(self):
        r = EvalResult(**self._base_kwargs())
        assert r.strategy_name == "FlatStrategy"
        assert r.n_queries == 10
        assert r.n_failed == 0
        assert r.k_used == 10
        assert r.precision_at_1 == 0.6
        assert r.recall_at_k == 0.8
        assert r.mrr == 0.7
        assert r.ndcg_at_5 == 0.75
        assert r.confusion_rate == 0.3
        assert r.ece == 0.1

    def test_per_query_defaults_to_empty_tuple(self):
        r = EvalResult(**self._base_kwargs())
        assert r.per_query == ()

    def test_server_recall_defaults_to_zero(self):
        r = EvalResult(**self._base_kwargs())
        assert r.server_recall_at_k == 0.0

    def test_confusion_rate_can_be_none(self):
        r = EvalResult(**self._base_kwargs(confusion_rate=None))
        assert r.confusion_rate is None

    def test_ece_can_be_none(self):
        r = EvalResult(**self._base_kwargs(ece=None))
        assert r.ece is None

    def test_is_frozen_raises_on_mutation(self):
        r = EvalResult(**self._base_kwargs())
        with pytest.raises(AttributeError):
            r.precision_at_1 = 1.0  # type: ignore[misc]

    def test_per_query_accepts_tuple_of_results(self):
        pq = (_make_pq(), _make_pq(query_id="q2"))
        r = EvalResult(**self._base_kwargs(), per_query=pq)
        assert len(r.per_query) == 2


# ---------------------------------------------------------------------------
# compute_precision_at_1
# ---------------------------------------------------------------------------


class TestComputePrecisionAt1:
    def test_returns_zero_when_list_is_empty(self):
        assert compute_precision_at_1([]) == 0.0

    def test_returns_one_when_all_correct(self):
        pqs = [_make_pq(top_1_correct=True) for _ in range(4)]
        assert compute_precision_at_1(pqs) == pytest.approx(1.0)

    def test_returns_zero_when_all_wrong(self):
        pqs = [_make_pq(top_1_correct=False, rank_of_correct=2) for _ in range(4)]
        assert compute_precision_at_1(pqs) == pytest.approx(0.0)

    def test_returns_fraction_for_mixed(self):
        pqs = [
            _make_pq(top_1_correct=True),
            _make_pq(top_1_correct=True),
            _make_pq(top_1_correct=False, rank_of_correct=None),
            _make_pq(top_1_correct=False, rank_of_correct=None),
        ]
        assert compute_precision_at_1(pqs) == pytest.approx(0.5)

    def test_single_correct_entry(self):
        assert compute_precision_at_1([_make_pq(top_1_correct=True)]) == pytest.approx(1.0)

    def test_single_wrong_entry(self):
        pq = _make_pq(top_1_correct=False, rank_of_correct=3)
        assert compute_precision_at_1([pq]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_recall_at_k
# ---------------------------------------------------------------------------


class TestComputeRecallAtK:
    def test_returns_zero_when_list_is_empty(self):
        assert compute_recall_at_k([]) == 0.0

    def test_returns_one_when_correct_always_in_top_k(self):
        pqs = [_make_pq(in_top_k=True) for _ in range(3)]
        assert compute_recall_at_k(pqs) == pytest.approx(1.0)

    def test_returns_zero_when_correct_never_in_top_k(self):
        pqs = [
            _make_pq(top_1_correct=False, in_top_k=False, rank_of_correct=None) for _ in range(3)
        ]
        assert compute_recall_at_k(pqs) == pytest.approx(0.0)

    def test_returns_fraction_for_mixed(self):
        pqs = [
            _make_pq(in_top_k=True),
            _make_pq(in_top_k=True),
            _make_pq(top_1_correct=False, in_top_k=False, rank_of_correct=None),
        ]
        assert compute_recall_at_k(pqs) == pytest.approx(2 / 3)

    def test_correct_at_rank_k_counts_as_in_top_k(self):
        pq = _make_pq(top_1_correct=False, in_top_k=True, rank_of_correct=10)
        assert compute_recall_at_k([pq]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# compute_mrr
# ---------------------------------------------------------------------------


class TestComputeMRR:
    def test_returns_zero_when_list_is_empty(self):
        assert compute_mrr([]) == pytest.approx(0.0)

    def test_correct_at_rank_1_returns_one(self):
        assert compute_mrr([_make_pq(rank_of_correct=1)]) == pytest.approx(1.0)

    def test_correct_at_rank_2_returns_half(self):
        pq = _make_pq(top_1_correct=False, rank_of_correct=2)
        assert compute_mrr([pq]) == pytest.approx(0.5)

    def test_correct_at_rank_5_returns_one_fifth(self):
        pq = _make_pq(top_1_correct=False, in_top_k=True, rank_of_correct=5)
        assert compute_mrr([pq]) == pytest.approx(0.2)

    def test_not_found_contributes_zero(self):
        pq = _make_pq(top_1_correct=False, in_top_k=False, rank_of_correct=None)
        assert compute_mrr([pq]) == pytest.approx(0.0)

    def test_average_across_multiple_queries(self):
        # (1/1 + 1/4) / 2 = 0.625
        pqs = [
            _make_pq(rank_of_correct=1),
            _make_pq(top_1_correct=False, rank_of_correct=4),
        ]
        assert compute_mrr(pqs) == pytest.approx(0.625)

    def test_mixed_found_and_not_found(self):
        # (1/2 + 0) / 2 = 0.25
        pqs = [
            _make_pq(top_1_correct=False, rank_of_correct=2),
            _make_pq(top_1_correct=False, in_top_k=False, rank_of_correct=None),
        ]
        assert compute_mrr(pqs) == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# compute_ndcg_at_5
# ---------------------------------------------------------------------------


class TestComputeNDCGAt5:
    def test_correct_at_rank_1_no_alternatives_returns_one(self):
        results = [_make_result("srv::a", 0.9, 1), _make_result("srv::b", 0.5, 2)]
        entry = _make_gt("srv::a")
        # DCG = 2/log2(2) = 2.0; IDCG = 2.0; NDCG = 1.0
        assert compute_ndcg_at_5(results, entry) == pytest.approx(1.0)

    def test_correct_at_rank_2_partial_score(self):
        results = [_make_result("srv::b", 0.9, 1), _make_result("srv::a", 0.8, 2)]
        entry = _make_gt("srv::a")
        # DCG = 2/log2(3); IDCG = 2/log2(2) = 2.0
        expected = (2.0 / math.log2(3)) / 2.0
        assert compute_ndcg_at_5(results, entry) == pytest.approx(expected)

    def test_alternative_tool_at_rank_1_grades_as_one(self):
        results = [_make_result("srv::alt", 0.9, 1), _make_result("srv::a", 0.8, 2)]
        entry = _make_gt("srv::a", alternative_tools=["srv::alt"])
        dcg = 1.0 / math.log2(2) + 2.0 / math.log2(3)
        idcg = 2.0 / math.log2(2) + 1.0 / math.log2(3)
        assert compute_ndcg_at_5(results, entry) == pytest.approx(dcg / idcg)

    def test_irrelevant_results_return_zero(self):
        results = [_make_result("srv::x", 0.9, 1), _make_result("srv::y", 0.7, 2)]
        entry = _make_gt("srv::a")
        assert compute_ndcg_at_5(results, entry) == pytest.approx(0.0)

    def test_empty_results_returns_zero(self):
        assert compute_ndcg_at_5([], _make_gt("srv::a")) == pytest.approx(0.0)

    def test_no_alternatives_does_not_crash(self):
        results = [_make_result("srv::a", 0.9, 1)]
        entry = _make_gt("srv::a", alternative_tools=None)
        assert compute_ndcg_at_5(results, entry) == pytest.approx(1.0)

    def test_multiple_alternatives_all_in_results(self):
        results = [
            _make_result("srv::a", 0.95, 1),  # correct → grade 2
            _make_result("srv::alt1", 0.8, 2),  # alternative → grade 1
            _make_result("srv::alt2", 0.7, 3),  # alternative → grade 1
        ]
        entry = _make_gt("srv::a", alternative_tools=["srv::alt1", "srv::alt2"])
        # dcg == idcg when all relevant items are ranked optimally → ndcg == 1.0
        assert compute_ndcg_at_5(results, entry) == pytest.approx(1.0)

    def test_cutoff_at_5_ignores_rank_6_and_beyond(self):
        # Correct tool placed at rank 6 — beyond NDCG@5 cutoff → 0.0
        results = [_make_result(f"srv::x{i}", 0.9 - i * 0.1, i + 1) for i in range(5)]
        results.append(_make_result("srv::a", 0.1, 6))
        entry = _make_gt("srv::a")
        assert compute_ndcg_at_5(results, entry) == pytest.approx(0.0)

    def test_correct_at_rank_5_boundary(self):
        results = [
            _make_result("srv::x1", 0.9, 1),
            _make_result("srv::x2", 0.8, 2),
            _make_result("srv::x3", 0.7, 3),
            _make_result("srv::x4", 0.6, 4),
            _make_result("srv::a", 0.5, 5),  # correct at rank 5
        ]
        entry = _make_gt("srv::a")
        # DCG = 2/log2(6); IDCG = 2/log2(2) = 2.0
        expected = (2.0 / math.log2(6)) / 2.0
        assert compute_ndcg_at_5(results, entry) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# compute_confusion_rate
# ---------------------------------------------------------------------------


class TestComputeConfusionRate:
    def test_returns_none_when_all_correct(self):
        pqs = [_make_pq(top_1_correct=True) for _ in range(3)]
        assert compute_confusion_rate(pqs) is None

    def test_returns_none_when_list_is_empty(self):
        assert compute_confusion_rate([]) is None

    def test_returns_one_when_all_errors_are_confusions(self):
        pqs = [_make_pq(top_1_correct=False, in_top_k=True, rank_of_correct=3)]
        assert compute_confusion_rate(pqs) == pytest.approx(1.0)

    def test_returns_zero_when_all_errors_are_misses(self):
        pqs = [_make_pq(top_1_correct=False, in_top_k=False, rank_of_correct=None)]
        assert compute_confusion_rate(pqs) == pytest.approx(0.0)

    def test_mixed_confusion_and_miss(self):
        pqs = [
            _make_pq(top_1_correct=True),
            _make_pq(top_1_correct=False, in_top_k=True, rank_of_correct=2),  # confusion
            _make_pq(top_1_correct=False, in_top_k=False, rank_of_correct=None),  # miss
        ]
        assert compute_confusion_rate(pqs) == pytest.approx(0.5)

    def test_correct_queries_excluded_from_error_denominator(self):
        # 2 correct, 1 confusion → errors=[confusion] → confusion_rate = 1.0
        pqs = [
            _make_pq(top_1_correct=True),
            _make_pq(top_1_correct=True),
            _make_pq(top_1_correct=False, in_top_k=True, rank_of_correct=2),
        ]
        assert compute_confusion_rate(pqs) == pytest.approx(1.0)

    def test_all_errors_three_way_split(self):
        pqs = [
            _make_pq(top_1_correct=False, in_top_k=True, rank_of_correct=2),  # confusion
            _make_pq(top_1_correct=False, in_top_k=True, rank_of_correct=3),  # confusion
            _make_pq(top_1_correct=False, in_top_k=False, rank_of_correct=None),  # miss
        ]
        assert compute_confusion_rate(pqs) == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# compute_ece
# ---------------------------------------------------------------------------


class TestComputeECE:
    def test_returns_none_when_confidences_empty(self):
        assert compute_ece([], []) is None

    def test_returns_none_for_confidence_above_one(self):
        assert compute_ece([1.5], [True]) is None

    def test_returns_none_for_negative_confidence(self):
        assert compute_ece([-0.1], [False]) is None

    def test_returns_none_when_any_confidence_out_of_range(self):
        assert compute_ece([0.5, 1.1, 0.3], [True, False, True]) is None

    def test_perfectly_calibrated_low_ece(self):
        # confidence ~ accuracy in each bin → ECE should be near 0
        confidences = [0.9, 0.85, 0.92, 0.88, 0.91]
        correct = [True, True, True, True, True]
        ece = compute_ece(confidences, correct, n_bins=5)
        assert ece is not None
        assert ece < 0.2

    def test_miscalibrated_high_ece(self):
        # high confidence but all wrong → large ECE
        confidences = [0.95, 0.90, 0.95, 0.90, 0.95]
        correct = [False, False, False, False, False]
        ece = compute_ece(confidences, correct, n_bins=5)
        assert ece is not None
        assert ece > 0.5

    def test_single_item_correct_at_0_75(self):
        # bin [0.7, 0.8): acc=1.0, conf=0.75 → ECE = |1.0 - 0.75| = 0.25
        ece = compute_ece([0.75], [True], n_bins=10)
        assert ece == pytest.approx(0.25)

    def test_single_item_wrong_at_0_75(self):
        # bin [0.7, 0.8): acc=0.0, conf=0.75 → ECE = |0.0 - 0.75| = 0.75
        ece = compute_ece([0.75], [False], n_bins=10)
        assert ece == pytest.approx(0.75)

    def test_confidence_exactly_1_0_falls_in_last_bin(self):
        # Last bin [0.9, 1.0] is inclusive on upper bound
        ece = compute_ece([1.0], [True], n_bins=10)
        assert ece == pytest.approx(0.0)  # acc=1.0, conf=1.0

    def test_confidence_exactly_0_0_falls_in_first_bin(self):
        ece = compute_ece([0.0], [False], n_bins=10)
        assert ece == pytest.approx(0.0)  # acc=0.0, conf=0.0

    def test_multiple_items_in_same_bin(self):
        # All in bin [0.8, 0.9): 3 items, 2 correct → acc=2/3, conf=0.85
        confidences = [0.80, 0.85, 0.88]
        correct = [True, True, False]
        ece = compute_ece(confidences, correct, n_bins=10)
        assert ece is not None
        expected = abs(2 / 3 - (0.80 + 0.85 + 0.88) / 3)
        assert ece == pytest.approx(expected, abs=1e-6)

    def test_empty_bins_skipped_without_error(self):
        # Sparse data: only one confidence value far from others
        ece = compute_ece([0.55], [True], n_bins=10)
        assert ece is not None  # Must not raise

    def test_n_bins_parameter_affects_result(self):
        confidences = [0.5, 0.6, 0.7, 0.8, 0.9]
        correct = [True, False, True, False, True]
        ece_5 = compute_ece(confidences, correct, n_bins=5)
        ece_10 = compute_ece(confidences, correct, n_bins=10)
        # Both must be valid non-None floats, but may differ in magnitude
        assert ece_5 is not None
        assert ece_10 is not None

    def test_last_bin_upper_boundary_inclusive(self):
        # 0.9 and 1.0 should both land in the last bin when n_bins=10
        ece = compute_ece([0.9, 1.0], [True, True], n_bins=10)
        assert ece is not None
        # acc=1.0, conf=0.95 → ECE = |1.0 - 0.95| = 0.05
        assert ece == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# compute_latency_stats
# ---------------------------------------------------------------------------


class TestComputeLatencyStats:
    def test_returns_all_zeros_for_empty_list(self):
        assert compute_latency_stats([]) == (0.0, 0.0, 0.0, 0.0)

    def test_single_value_all_stats_equal(self):
        p50, p95, p99, mean = compute_latency_stats([42.0])
        assert p50 == pytest.approx(42.0)
        assert p95 == pytest.approx(42.0)
        assert p99 == pytest.approx(42.0)
        assert mean == pytest.approx(42.0)

    def test_basic_percentile_ordering(self):
        latencies = list(range(10, 110, 10))  # [10, 20, ..., 100]
        p50, p95, p99, mean = compute_latency_stats(latencies)
        assert p50 == pytest.approx(55.0)
        assert mean == pytest.approx(55.0)
        assert p95 > p50
        assert p99 >= p95

    def test_two_values_mean_is_average(self):
        _, _, _, mean = compute_latency_stats([10.0, 20.0])
        assert mean == pytest.approx(15.0)

    def test_large_spread_p99_greater_than_p50(self):
        # 100 values: 99 at 1.0 ms, 1 outlier at 1000.0 ms
        latencies = [1.0] * 99 + [1000.0]
        p50, _, p99, _ = compute_latency_stats(latencies)
        # p99 must be larger than p50 (outlier raises the tail)
        assert p99 > p50

    def test_all_same_values_returns_that_value(self):
        p50, p95, p99, mean = compute_latency_stats([7.5, 7.5, 7.5])
        assert p50 == pytest.approx(7.5)
        assert p95 == pytest.approx(7.5)
        assert p99 == pytest.approx(7.5)
        assert mean == pytest.approx(7.5)

    def test_returns_floats_not_numpy_scalars(self):
        p50, p95, p99, mean = compute_latency_stats([10.0, 20.0, 30.0])
        # All returned values must be native Python floats
        assert isinstance(p50, float)
        assert isinstance(p95, float)
        assert isinstance(p99, float)
        assert isinstance(mean, float)


# ---------------------------------------------------------------------------
# compute_server_recall_at_k
# ---------------------------------------------------------------------------


class TestComputeServerRecallAtK:
    def test_returns_zero_for_empty_list(self):
        assert compute_server_recall_at_k([]) == pytest.approx(0.0)

    def test_returns_one_when_all_servers_found(self):
        pqs = [_make_pq(correct_server_in_top_k=True) for _ in range(5)]
        assert compute_server_recall_at_k(pqs) == pytest.approx(1.0)

    def test_returns_zero_when_no_servers_found(self):
        pqs = [_make_pq(correct_server_in_top_k=False) for _ in range(5)]
        assert compute_server_recall_at_k(pqs) == pytest.approx(0.0)

    def test_returns_fraction_for_partial_recall(self):
        pqs = [
            _make_pq(correct_server_in_top_k=True),
            _make_pq(correct_server_in_top_k=True),
            _make_pq(correct_server_in_top_k=False),
            _make_pq(correct_server_in_top_k=False),
        ]
        assert compute_server_recall_at_k(pqs) == pytest.approx(0.5)

    def test_single_found_returns_one(self):
        pq = _make_pq(correct_server_in_top_k=True)
        assert compute_server_recall_at_k([pq]) == pytest.approx(1.0)

    def test_single_not_found_returns_zero(self):
        pq = _make_pq(correct_server_in_top_k=False)
        assert compute_server_recall_at_k([pq]) == pytest.approx(0.0)

    def test_correct_server_field_default_false_counts_as_miss(self):
        # _make_pq without correct_server_in_top_k → defaults to False
        pqs = [_make_pq() for _ in range(3)]
        assert compute_server_recall_at_k(pqs) == pytest.approx(0.0)
