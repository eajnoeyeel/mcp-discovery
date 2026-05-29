"""E2E harness for operational signals pipeline.

Tests the full search pipeline with operability features:
gate → score merge → enrichment → confidence.
Includes repeated execution and degraded mode checks.
"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from mcp_discovery.analytics.insight_engine import InsightEngine
from mcp_discovery.operability.models import (
    FreshnessTriple,
    ToolOperabilitySnapshot,
    build_enrichment,
    compute_operability_float,
)
from service.rag.cache import QueryCache
from service.rag.service import RAGSearchResult, RAGService
from service.rag.tests.conftest import make_result

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    tool_id: str,
    server_id: str,
    *,
    status: str = "active",
    call_count: int = 100,
    call_count_7d: int = 30,
    success_rate: float | None = 0.95,
    timeout_rate: float | None = 0.01,
    avg_latency_ms: float | None = 200.0,
    p95_latency_ms: float | None = 500.0,
    min_support: int = 20,
    freshness: FreshnessTriple | None = None,
) -> ToolOperabilitySnapshot:
    op_score = compute_operability_float(
        success_rate=success_rate,
        avg_latency_ms=avg_latency_ms,
        timeout_rate=timeout_rate,
    )
    return ToolOperabilitySnapshot(
        tool_id=tool_id,
        server_id=server_id,
        status=status,
        call_count=call_count,
        call_count_7d=call_count_7d,
        success_rate=success_rate,
        timeout_rate=timeout_rate,
        avg_latency_ms=avg_latency_ms,
        p95_latency_ms=p95_latency_ms,
        min_support=min_support,
        operability_score=op_score,
        snapshot_version=1,
        computed_at=datetime.now(timezone.utc),
        freshness=freshness
        or FreshnessTriple(
            last_successful_call_at=datetime.now(timezone.utc),
            source_updated_at=datetime.now(timezone.utc),
            indexed_at=datetime.now(timezone.utc),
        ),
    )


class MockOperabilityCache:
    """In-process mock that simulates OperabilityCache behavior."""

    def __init__(
        self,
        snapshots: dict[str, ToolOperabilitySnapshot],
        *,
        fail_on_refresh: bool = False,
    ) -> None:
        self._snapshots = snapshots
        self._fail_on_refresh = fail_on_refresh
        self.call_count = 0

    async def get_bulk(self, tool_ids: list[str]) -> dict[str, ToolOperabilitySnapshot]:
        self.call_count += 1
        if self._fail_on_refresh:
            raise ConnectionError("Supabase unreachable (simulated)")
        return {tid: self._snapshots[tid] for tid in tool_ids if tid in self._snapshots}


def _build_operability_service(
    strategy_results=None,
    strategy_error=None,
    snapshots=None,
    cache_fail=False,
    gap_threshold=0.15,
    reranker=None,
    cache_ttl=0,
):
    """Build a RAGService wired with MockOperabilityCache."""
    strategy = AsyncMock()
    if strategy_error is not None:
        strategy.search = AsyncMock(side_effect=strategy_error)
    else:
        strategy.search = AsyncMock(return_value=strategy_results or [])

    op_cache = (
        MockOperabilityCache(snapshots or {}, fail_on_refresh=cache_fail)
        if snapshots is not None or cache_fail
        else None
    )
    cache = QueryCache(ttl_seconds=cache_ttl) if cache_ttl > 0 else None

    return RAGService(
        strategy=strategy,
        fallback=None,
        cache=cache,
        confidence_gap_threshold=gap_threshold,
        reranker=reranker,
        operability_cache=op_cache,
    )


# ---------------------------------------------------------------------------
# E2E Scenarios
# ---------------------------------------------------------------------------


class TestOperabilityE2EHarness:
    """Full pipeline E2E with operability signals."""

    async def test_e2e_gate_filters_quarantined_tool(self):
        """Quarantined tool removed from results even if top-ranked by embedding."""
        snapshots = {
            "srv1::tool_a": _make_snapshot("srv1::tool_a", "srv1", status="quarantined"),
            "srv2::tool_b": _make_snapshot("srv2::tool_b", "srv2", status="active"),
        }
        service = _build_operability_service(
            strategy_results=[
                make_result(server_id="srv1", tool_name="tool_a", score=0.95, rank=1),
                make_result(server_id="srv2", tool_name="tool_b", score=0.70, rank=2),
            ],
            snapshots=snapshots,
        )
        resp = await service.search("find a tool", top_k=3)

        assert isinstance(resp, RAGSearchResult)
        tool_ids = [r.tool.tool_id for r in resp.results]
        assert "srv1::tool_a" not in tool_ids, "Quarantined tool must be filtered"
        assert "srv2::tool_b" in tool_ids

    async def test_e2e_score_merge_reorders_results(self):
        """Tool with lower retrieval but higher operability should rise in rank."""
        snapshots = {
            "srv1::tool_a": _make_snapshot(
                "srv1::tool_a",
                "srv1",
                success_rate=0.50,
                avg_latency_ms=5000.0,
                timeout_rate=0.2,
            ),
            "srv2::tool_b": _make_snapshot(
                "srv2::tool_b",
                "srv2",
                success_rate=0.99,
                avg_latency_ms=50.0,
                timeout_rate=0.0,
            ),
        }
        service = _build_operability_service(
            strategy_results=[
                make_result(server_id="srv1", tool_name="tool_a", score=0.85, rank=1),
                make_result(server_id="srv2", tool_name="tool_b", score=0.75, rank=2),
            ],
            snapshots=snapshots,
        )
        resp = await service.search("find tool", top_k=3)

        # tool_b has much better operability, should rank higher after merge
        assert resp.results[0].tool.tool_id == "srv2::tool_b"
        assert resp.results[0].retrieval_score == 0.75
        assert resp.results[0].score != 0.75  # composite score

    async def test_e2e_enrichment_metadata_attached(self):
        """Search results have operability enrichment metadata."""
        snapshots = {
            "srv1::tool_a": _make_snapshot(
                "srv1::tool_a",
                "srv1",
                success_rate=0.92,
                avg_latency_ms=150.0,
            ),
        }
        service = _build_operability_service(
            strategy_results=[
                make_result(server_id="srv1", tool_name="tool_a", score=0.9, rank=1),
            ],
            snapshots=snapshots,
        )
        resp = await service.search("tool search", top_k=3)

        result = resp.results[0]
        assert result.operability is not None
        assert result.operability.status == "active"
        assert result.operability.cold_start is False
        assert result.operability.success_rate == 0.92
        assert result.operability.operability_grade in ("A", "B", "C", "D", "F")

    async def test_e2e_cold_start_tool_passes_gate(self):
        """Cold-start tools (low call_count) pass through gate and enrichment."""
        snapshots = {
            "srv1::new_tool": _make_snapshot(
                "srv1::new_tool",
                "srv1",
                call_count=3,
                call_count_7d=1,
                success_rate=None,
                timeout_rate=None,
                avg_latency_ms=None,
                status="active",
            ),
        }
        service = _build_operability_service(
            strategy_results=[
                make_result(server_id="srv1", tool_name="new_tool", score=0.8, rank=1),
            ],
            snapshots=snapshots,
        )
        resp = await service.search("new tool", top_k=3)

        assert len(resp.results) == 1
        assert resp.results[0].operability is not None
        assert resp.results[0].operability.cold_start is True

    async def test_e2e_degraded_mode_cache_failure(self):
        """When OperabilityCache fails, search degrades to relevance-only."""
        service = _build_operability_service(
            strategy_results=[
                make_result(server_id="srv1", tool_name="tool_a", score=0.9, rank=1),
                make_result(server_id="srv2", tool_name="tool_b", score=0.7, rank=2),
            ],
            cache_fail=True,
        )
        resp = await service.search("degraded query", top_k=3)

        # Should not crash — results returned with original scores
        assert len(resp.results) >= 1
        # No enrichment when cache fails
        assert resp.results[0].operability is None

    async def test_e2e_unknown_tools_pass_through(self):
        """Tools not in snapshot cache pass through gate unblocked."""
        snapshots = {
            "srv1::known_tool": _make_snapshot("srv1::known_tool", "srv1"),
        }
        service = _build_operability_service(
            strategy_results=[
                make_result(server_id="srv1", tool_name="known_tool", score=0.8, rank=1),
                make_result(server_id="srv2", tool_name="unknown_tool", score=0.75, rank=2),
            ],
            snapshots=snapshots,
        )
        resp = await service.search("mixed query", top_k=3)

        tool_ids = [r.tool.tool_id for r in resp.results]
        assert "srv2::unknown_tool" in tool_ids, "Unknown tools should pass through"

    async def test_e2e_all_blocked_statuses_filtered(self):
        """All BLOCKED_STATUSES are filtered by hard gate."""
        blocked = ["quarantined", "unreachable", "deprecated", "stale"]
        for status in blocked:
            snapshots = {
                "srv1::blocked": _make_snapshot("srv1::blocked", "srv1", status=status),
                "srv2::active": _make_snapshot("srv2::active", "srv2", status="active"),
            }
            service = _build_operability_service(
                strategy_results=[
                    make_result(server_id="srv1", tool_name="blocked", score=0.99, rank=1),
                    make_result(server_id="srv2", tool_name="active", score=0.5, rank=2),
                ],
                snapshots=snapshots,
            )
            resp = await service.search(f"test {status}", top_k=3)
            tool_ids = [r.tool.tool_id for r in resp.results]
            assert "srv1::blocked" not in tool_ids, f"Status '{status}' should be blocked"

    async def test_e2e_latency_within_bounds(self):
        """Full pipeline with operability adds negligible latency."""
        snapshots = {
            f"srv{i}::tool_{i}": _make_snapshot(f"srv{i}::tool_{i}", f"srv{i}") for i in range(10)
        }
        results = [
            make_result(
                server_id=f"srv{i}",
                tool_name=f"tool_{i}",
                score=1.0 - i * 0.05,
                rank=i + 1,
            )
            for i in range(10)
        ]
        service = _build_operability_service(
            strategy_results=results,
            snapshots=snapshots,
        )

        t_start = time.perf_counter()
        resp = await service.search("latency test", top_k=3)
        elapsed_ms = (time.perf_counter() - t_start) * 1000

        assert resp.latency_ms > 0
        # Gate + score merge + enrichment should be sub-millisecond on 10 items
        # Total including mock strategy overhead should be < 100ms
        assert elapsed_ms < 100, f"Pipeline too slow: {elapsed_ms:.1f}ms"


class TestOperabilityRepeatedExecution:
    """Repeated execution stability — same input → consistent output."""

    REPETITIONS = 5

    async def test_repeated_gate_consistency(self):
        """Gate produces identical results across repeated runs."""
        snapshots = {
            "srv1::good": _make_snapshot("srv1::good", "srv1", status="active"),
            "srv2::bad": _make_snapshot("srv2::bad", "srv2", status="quarantined"),
        }
        service = _build_operability_service(
            strategy_results=[
                make_result(server_id="srv1", tool_name="good", score=0.9, rank=1),
                make_result(server_id="srv2", tool_name="bad", score=0.95, rank=2),
            ],
            snapshots=snapshots,
        )

        results_per_run = []
        for _ in range(self.REPETITIONS):
            resp = await service.search("stable query", top_k=3)
            results_per_run.append([r.tool.tool_id for r in resp.results])

        for run in results_per_run[1:]:
            assert run == results_per_run[0], "Gate results should be deterministic"

    async def test_repeated_score_merge_consistency(self):
        """Score merge produces identical ordering across repeated runs."""
        snapshots = {
            "srv1::a": _make_snapshot("srv1::a", "srv1", success_rate=0.5),
            "srv2::b": _make_snapshot("srv2::b", "srv2", success_rate=0.99),
        }
        service = _build_operability_service(
            strategy_results=[
                make_result(server_id="srv1", tool_name="a", score=0.9, rank=1),
                make_result(server_id="srv2", tool_name="b", score=0.8, rank=2),
            ],
            snapshots=snapshots,
        )

        scores_per_run = []
        for _ in range(self.REPETITIONS):
            resp = await service.search("consistency check", top_k=3)
            scores_per_run.append([(r.tool.tool_id, r.score) for r in resp.results])

        for run in scores_per_run[1:]:
            assert run == scores_per_run[0], "Score merge should be deterministic"


class TestInsightEngineE2E:
    """E2E for InsightEngine across different tool profiles."""

    def _engine(self) -> InsightEngine:
        return InsightEngine()

    def test_healthy_tool_zero_insights(self):
        snap = _make_snapshot("srv::healthy", "srv")
        insights = self._engine().analyze(snap)
        assert len(insights) == 0

    def test_unhealthy_tool_multiple_insights(self):
        snap = _make_snapshot(
            "srv::sick",
            "srv",
            success_rate=0.3,
            timeout_rate=0.25,
            avg_latency_ms=8000.0,
            p95_latency_ms=12000.0,
        )
        insights = self._engine().analyze(snap)
        categories = {i.category for i in insights}
        assert "success_rate" in categories
        assert "timeout" in categories
        assert all(i.data for i in insights), "All insights must have data"

    def test_cold_start_tool_insight(self):
        snap = _make_snapshot(
            "srv::new",
            "srv",
            call_count=0,
            call_count_7d=0,
            success_rate=None,
            timeout_rate=None,
            avg_latency_ms=None,
            freshness=FreshnessTriple(
                source_updated_at=datetime.now(timezone.utc) - timedelta(days=15),
            ),
        )
        insights = self._engine().analyze(snap)
        assert any(i.category == "cold_start" for i in insights)

    def test_stale_tool_freshness_insight(self):
        snap = _make_snapshot(
            "srv::stale",
            "srv",
            freshness=FreshnessTriple(
                last_successful_call_at=datetime.now(timezone.utc) - timedelta(days=120),
                source_updated_at=datetime.now(timezone.utc),
                indexed_at=datetime.now(timezone.utc),
            ),
        )
        insights = self._engine().analyze(snap)
        assert any(i.category == "freshness" for i in insights)

    def test_short_description_insight(self):
        snap = _make_snapshot("srv::poor_desc", "srv")
        insights = self._engine().analyze(snap, description="A tool")
        assert any(i.category == "description" for i in insights)

    def test_quarantined_status_critical_insight(self):
        snap = _make_snapshot("srv::down", "srv", status="quarantined")
        insights = self._engine().analyze(snap)
        assert any(i.severity == "critical" and i.category == "health" for i in insights)

    def test_insight_stability_across_runs(self):
        """Same snapshot → same insights every time."""
        snap = _make_snapshot(
            "srv::unstable",
            "srv",
            success_rate=0.5,
            timeout_rate=0.15,
        )
        engine = self._engine()
        baseline = engine.analyze(snap)
        for _ in range(5):
            run = engine.analyze(snap)
            assert len(run) == len(baseline)
            assert [i.category for i in run] == [i.category for i in baseline]


class TestOperabilityModelsE2E:
    """E2E for operability model computation and enrichment."""

    def test_operability_float_ranges(self):
        """All valid inputs produce [0, 1] output."""
        test_cases = [
            {"success_rate": 1.0, "avg_latency_ms": 0, "timeout_rate": 0},
            {"success_rate": 0.0, "avg_latency_ms": 10000, "timeout_rate": 1.0},
            {"success_rate": 0.5, "avg_latency_ms": 5000, "timeout_rate": 0.1},
            {"success_rate": None, "avg_latency_ms": None, "timeout_rate": None},
        ]
        for tc in test_cases:
            score = compute_operability_float(**tc)
            assert 0.0 <= score <= 1.0, f"Out of range for {tc}: {score}"

    def test_enrichment_roundtrip(self):
        """Snapshot → enrichment → grade, all fields populated."""
        snap = _make_snapshot("srv::tool", "srv", success_rate=0.85)
        enrichment = build_enrichment(snap)
        assert enrichment is not None
        assert enrichment.status == "active"
        assert enrichment.success_rate == 0.85
        assert enrichment.operability_grade is not None

    def test_enrichment_none_passthrough(self):
        assert build_enrichment(None) is None

    def test_freshness_triple_all_dimensions(self):
        now = datetime.now(timezone.utc)
        ft = FreshnessTriple(
            source_updated_at=now - timedelta(days=5),
            indexed_at=now - timedelta(days=3),
            last_successful_call_at=now - timedelta(days=1),
        )
        assert ft.source_freshness_days == 5
        assert ft.index_freshness_days == 3
        assert ft.operational_freshness_days == 1
