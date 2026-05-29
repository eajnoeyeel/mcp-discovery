"""Unit tests for evaluation metric functions."""

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

from .conftest import _make_gt, _make_pq, _make_result


class TestDataclasses:
    def test_per_query_result_fields(self):
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
        assert r.rank_of_correct == 1
        assert r.confidence == 0.9
        assert r.latency_ms == 42.5
        assert r.retrieved_tool_ids == ("srv::a", "srv::b")

    def test_per_query_result_is_frozen(self):
        r = PerQueryResult(
            query_id="gt-001",
            top_1_correct=True,
            in_top_k=True,
            rank_of_correct=1,
            confidence=0.9,
            latency_ms=42.5,
            retrieved_tool_ids=("srv::a",),
        )
        with pytest.raises(AttributeError):
            r.query_id = "changed"  # type: ignore[misc]

    def test_eval_result_defaults(self):
        r = EvalResult(
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
        assert r.strategy_name == "FlatStrategy"
        assert r.precision_at_1 == 0.6
        assert r.per_query == ()  # default empty tuple

    def test_eval_result_is_frozen(self):
        r = EvalResult(
            strategy_name="FlatStrategy",
            n_queries=0,
            n_failed=0,
            k_used=10,
            precision_at_1=0.0,
            recall_at_k=0.0,
            mrr=0.0,
            ndcg_at_5=0.0,
            confusion_rate=None,
            ece=0.0,
            latency_p50=0.0,
            latency_p95=0.0,
            latency_p99=0.0,
            latency_mean=0.0,
        )
        with pytest.raises(AttributeError):
            r.precision_at_1 = 1.0  # type: ignore[misc]

    def test_eval_result_confusion_rate_none(self):
        r = EvalResult(
            strategy_name="FlatStrategy",
            n_queries=1,
            n_failed=0,
            k_used=10,
            precision_at_1=1.0,
            recall_at_k=1.0,
            mrr=1.0,
            ndcg_at_5=1.0,
            confusion_rate=None,
            ece=0.0,
            latency_p50=10.0,
            latency_p95=10.0,
            latency_p99=10.0,
            latency_mean=10.0,
        )
        assert r.confusion_rate is None


# ── Rank-based metrics ───────────────────────────────────────────────────────


class TestPrecisionAt1:
    def test_all_correct(self):
        assert compute_precision_at_1([_make_pq(top_1_correct=True)]) == 1.0

    def test_all_wrong(self):
        assert compute_precision_at_1([_make_pq(top_1_correct=False, rank_of_correct=2)]) == 0.0

    def test_mixed(self):
        pqs = [_make_pq(top_1_correct=True), _make_pq(top_1_correct=False, rank_of_correct=None)]
        assert compute_precision_at_1(pqs) == pytest.approx(0.5)

    def test_empty(self):
        assert compute_precision_at_1([]) == 0.0


class TestRecallAtK:
    def test_correct_in_top_k(self):
        pq = _make_pq(top_1_correct=False, in_top_k=True, rank_of_correct=3)
        assert compute_recall_at_k([pq]) == 1.0

    def test_correct_not_in_top_k(self):
        pq = _make_pq(top_1_correct=False, in_top_k=False, rank_of_correct=None)
        assert compute_recall_at_k([pq]) == 0.0

    def test_empty(self):
        assert compute_recall_at_k([]) == 0.0


class TestMRR:
    def test_correct_at_rank_1(self):
        assert compute_mrr([_make_pq(rank_of_correct=1)]) == pytest.approx(1.0)

    def test_correct_at_rank_2(self):
        assert compute_mrr([_make_pq(top_1_correct=False, rank_of_correct=2)]) == pytest.approx(0.5)

    def test_not_found(self):
        pq = _make_pq(top_1_correct=False, in_top_k=False, rank_of_correct=None)
        assert compute_mrr([pq]) == pytest.approx(0.0)

    def test_mixed(self):
        # (1/1 + 1/4) / 2 = 0.625
        pqs = [_make_pq(rank_of_correct=1), _make_pq(top_1_correct=False, rank_of_correct=4)]
        assert compute_mrr(pqs) == pytest.approx(0.625)

    def test_empty(self):
        assert compute_mrr([]) == 0.0


class TestNDCGAt5:
    def test_correct_at_rank_1_no_alternatives(self):
        results = [_make_result("srv::a", 0.9, 1), _make_result("srv::b", 0.5, 2)]
        entry = _make_gt("srv::a")
        # DCG = 2/log2(2) = 2.0; IDCG = 2.0; NDCG = 1.0
        assert compute_ndcg_at_5(results, entry) == pytest.approx(1.0)

    def test_correct_at_rank_2(self):
        results = [_make_result("srv::b", 0.9, 1), _make_result("srv::a", 0.8, 2)]
        entry = _make_gt("srv::a")
        # DCG = 0 + 2/log2(3); IDCG = 2/log2(2) = 2.0
        expected = (2.0 / math.log2(3)) / 2.0
        assert compute_ndcg_at_5(results, entry) == pytest.approx(expected)

    def test_alternative_at_rank_1(self):
        results = [_make_result("srv::alt", 0.9, 1), _make_result("srv::a", 0.8, 2)]
        entry = _make_gt("srv::a", alternative_tools=["srv::alt"])
        # DCG = 1/log2(2) + 2/log2(3); IDCG = 2/log2(2) + 1/log2(3)
        dcg = 1.0 / math.log2(2) + 2.0 / math.log2(3)
        idcg = 2.0 / math.log2(2) + 1.0 / math.log2(3)
        assert compute_ndcg_at_5(results, entry) == pytest.approx(dcg / idcg)

    def test_not_found_returns_zero(self):
        results = [_make_result("srv::b", 0.9, 1)]
        entry = _make_gt("srv::a")
        assert compute_ndcg_at_5(results, entry) == pytest.approx(0.0)

    def test_empty_results_returns_zero(self):
        assert compute_ndcg_at_5([], _make_gt("srv::a")) == pytest.approx(0.0)


# ── Statistical metrics ──────────────────────────────────────────────────────


class TestConfusionRate:
    def test_all_correct_returns_none(self):
        assert compute_confusion_rate([_make_pq(top_1_correct=True)]) is None

    def test_empty_returns_none(self):
        assert compute_confusion_rate([]) is None

    def test_wrong_but_in_top_k_is_confusion(self):
        pqs = [_make_pq(top_1_correct=False, in_top_k=True, rank_of_correct=3)]
        assert compute_confusion_rate(pqs) == pytest.approx(1.0)

    def test_wrong_and_not_in_top_k_is_miss(self):
        pqs = [_make_pq(top_1_correct=False, in_top_k=False, rank_of_correct=None)]
        assert compute_confusion_rate(pqs) == pytest.approx(0.0)

    def test_half_confusion_half_miss(self):
        pqs = [
            _make_pq(top_1_correct=True),  # correct — excluded from errors
            _make_pq(top_1_correct=False, in_top_k=True, rank_of_correct=2),  # confusion
            _make_pq(top_1_correct=False, in_top_k=False, rank_of_correct=None),  # miss
        ]
        assert compute_confusion_rate(pqs) == pytest.approx(0.5)


class TestECE:
    def test_high_confidence_all_correct_low_ece(self):
        confidences = [0.9, 0.85, 0.92, 0.88, 0.91]
        correct = [True, True, True, True, True]
        assert compute_ece(confidences, correct, n_bins=5) < 0.2

    def test_high_confidence_all_wrong_high_ece(self):
        confidences = [0.95, 0.90, 0.95, 0.90, 0.95]
        correct = [False, False, False, False, False]
        assert compute_ece(confidences, correct, n_bins=5) > 0.5

    def test_empty_returns_none(self):
        assert compute_ece([], [], n_bins=10) is None

    def test_single_item(self):
        # One item in bin [0.7, 0.8): acc=1.0, conf=0.75 -> ECE = |1.0 - 0.75| = 0.25
        ece = compute_ece([0.75], [True], n_bins=10)
        assert ece == pytest.approx(0.25)

    def test_confidence_exactly_1_0(self):
        # Boundary: 1.0 falls in the last bin [0.9, 1.0]
        ece = compute_ece([1.0], [True], n_bins=10)
        assert ece == pytest.approx(0.0)  # acc=1.0, conf=1.0

    def test_confidence_exactly_0_0(self):
        # Boundary: 0.0 falls in the first bin [0.0, 0.1)
        ece = compute_ece([0.0], [False], n_bins=10)
        assert ece == pytest.approx(0.0)  # acc=0.0, conf=0.0

    def test_out_of_range_returns_none(self):
        """Uncalibrated confidences (>1.0) return None instead of raising."""
        assert compute_ece([1.5], [True], n_bins=10) is None

    def test_negative_confidence_returns_none(self):
        """Uncalibrated confidences (<0.0) return None instead of raising."""
        assert compute_ece([-0.1, 0.5], [True, False], n_bins=10) is None


class TestLatencyStats:
    def test_basic_percentiles(self):
        latencies = list(range(10, 110, 10))  # [10, 20, ..., 100]
        p50, p95, p99, mean = compute_latency_stats(latencies)
        assert p50 == pytest.approx(55.0)
        assert mean == pytest.approx(55.0)
        assert p95 > p50
        assert p99 >= p95

    def test_single_value(self):
        p50, p95, p99, mean = compute_latency_stats([42.0])
        assert p50 == pytest.approx(42.0)
        assert p95 == pytest.approx(42.0)
        assert p99 == pytest.approx(42.0)
        assert mean == pytest.approx(42.0)

    def test_empty_returns_all_zeros(self):
        assert compute_latency_stats([]) == (0.0, 0.0, 0.0, 0.0)


class TestServerRecallAtK:
    def test_all_servers_found(self):
        pq = [_make_pq(correct_server_in_top_k=True) for _ in range(5)]
        assert compute_server_recall_at_k(pq) == pytest.approx(1.0)

    def test_no_servers_found(self):
        pq = [_make_pq(correct_server_in_top_k=False) for _ in range(5)]
        assert compute_server_recall_at_k(pq) == pytest.approx(0.0)

    def test_partial_server_recall(self):
        pq = [
            _make_pq(correct_server_in_top_k=True),
            _make_pq(correct_server_in_top_k=True),
            _make_pq(correct_server_in_top_k=False),
            _make_pq(correct_server_in_top_k=False),
        ]
        assert compute_server_recall_at_k(pq) == pytest.approx(0.5)

    def test_empty_returns_zero(self):
        assert compute_server_recall_at_k([]) == pytest.approx(0.0)

    def test_default_field_is_false(self):
        pq = _make_pq()  # correct_server_in_top_k defaults to False
        assert pq.correct_server_in_top_k is False
