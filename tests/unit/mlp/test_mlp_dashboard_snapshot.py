"""Tests for MLP Provider Analytics — Dashboard Snapshots and Search Simulation."""

from __future__ import annotations

import pytest

# ============================================================
# 1. Dashboard Snapshot — build_provider_snapshot
# ============================================================


class TestBuildProviderSnapshot:
    """Tests for build_provider_snapshot aggregation logic."""

    def test_aggregates_geo_scores_basic(self) -> None:
        from service.analytics.snapshots import build_provider_snapshot

        snapshot = build_provider_snapshot(
            server_id="srv",
            tools=[
                {"tool_id": "srv::a", "geo_score": {"total": 0.6}},
                {"tool_id": "srv::b", "geo_score": {"total": 0.8}},
            ],
        )
        assert snapshot["server_id"] == "srv"
        assert snapshot["tool_count"] == 2
        assert snapshot["avg_geo_score"] == pytest.approx(0.7, abs=1e-4)

    def test_includes_min_max_scores(self) -> None:
        from service.analytics.snapshots import build_provider_snapshot

        snapshot = build_provider_snapshot(
            server_id="test-server",
            tools=[
                {"tool_id": "test-server::x", "geo_score": {"total": 0.3}},
                {"tool_id": "test-server::y", "geo_score": {"total": 0.9}},
                {"tool_id": "test-server::z", "geo_score": {"total": 0.6}},
            ],
        )
        assert snapshot["min_geo_score"] == pytest.approx(0.3, abs=1e-4)
        assert snapshot["max_geo_score"] == pytest.approx(0.9, abs=1e-4)

    def test_counts_low_scoring_tools(self) -> None:
        """Tools with total GEO score < 0.5 should be counted as low_score."""
        from service.analytics.snapshots import build_provider_snapshot

        snapshot = build_provider_snapshot(
            server_id="srv",
            tools=[
                {"tool_id": "srv::a", "geo_score": {"total": 0.2}},
                {"tool_id": "srv::b", "geo_score": {"total": 0.49}},
                {"tool_id": "srv::c", "geo_score": {"total": 0.5}},
                {"tool_id": "srv::d", "geo_score": {"total": 0.8}},
            ],
        )
        assert snapshot["low_score_count"] == 2

    def test_empty_tools_list(self) -> None:
        from service.analytics.snapshots import build_provider_snapshot

        snapshot = build_provider_snapshot(server_id="empty", tools=[])
        assert snapshot["server_id"] == "empty"
        assert snapshot["tool_count"] == 0
        assert snapshot["avg_geo_score"] == 0.0
        assert snapshot["min_geo_score"] == 0.0
        assert snapshot["max_geo_score"] == 0.0
        assert snapshot["low_score_count"] == 0

    def test_handles_missing_geo_score(self) -> None:
        """Tools without geo_score should default to 0.0 total."""
        from service.analytics.snapshots import build_provider_snapshot

        snapshot = build_provider_snapshot(
            server_id="srv",
            tools=[
                {"tool_id": "srv::a"},
                {"tool_id": "srv::b", "geo_score": {"total": 0.8}},
            ],
        )
        assert snapshot["tool_count"] == 2
        assert snapshot["avg_geo_score"] == pytest.approx(0.4, abs=1e-4)
        assert snapshot["low_score_count"] == 1  # 0.0 < 0.5

    def test_handles_none_geo_score(self) -> None:
        from service.analytics.snapshots import build_provider_snapshot

        snapshot = build_provider_snapshot(
            server_id="srv",
            tools=[
                {"tool_id": "srv::a", "geo_score": None},
                {"tool_id": "srv::b", "geo_score": {"total": 0.6}},
            ],
        )
        assert snapshot["tool_count"] == 2
        assert snapshot["avg_geo_score"] == pytest.approx(0.3, abs=1e-4)

    def test_includes_dimension_averages(self) -> None:
        """Snapshot should include per-dimension average scores."""
        from service.analytics.snapshots import build_provider_snapshot

        snapshot = build_provider_snapshot(
            server_id="srv",
            tools=[
                {
                    "tool_id": "srv::a",
                    "geo_score": {
                        "total": 0.5,
                        "clarity": 0.8,
                        "disambiguation": 0.2,
                        "parameter_coverage": 0.6,
                        "boundary": 0.4,
                        "stats": 0.3,
                        "precision": 0.7,
                    },
                },
                {
                    "tool_id": "srv::b",
                    "geo_score": {
                        "total": 0.7,
                        "clarity": 0.6,
                        "disambiguation": 0.4,
                        "parameter_coverage": 0.8,
                        "boundary": 0.6,
                        "stats": 0.5,
                        "precision": 0.3,
                    },
                },
            ],
        )
        dims = snapshot["dimension_averages"]
        assert dims["clarity"] == pytest.approx(0.7, abs=1e-4)
        assert dims["disambiguation"] == pytest.approx(0.3, abs=1e-4)
        assert dims["parameter_coverage"] == pytest.approx(0.7, abs=1e-4)
        assert dims["boundary"] == pytest.approx(0.5, abs=1e-4)
        assert dims["stats"] == pytest.approx(0.4, abs=1e-4)
        assert dims["precision"] == pytest.approx(0.5, abs=1e-4)

    def test_single_tool(self) -> None:
        from service.analytics.snapshots import build_provider_snapshot

        snapshot = build_provider_snapshot(
            server_id="srv",
            tools=[{"tool_id": "srv::only", "geo_score": {"total": 0.75}}],
        )
        assert snapshot["tool_count"] == 1
        assert snapshot["avg_geo_score"] == pytest.approx(0.75, abs=1e-4)
        assert snapshot["min_geo_score"] == pytest.approx(0.75, abs=1e-4)
        assert snapshot["max_geo_score"] == pytest.approx(0.75, abs=1e-4)
        assert snapshot["low_score_count"] == 0


# ============================================================
# 2. Batch Snapshot — build_all_snapshots
# ============================================================


class TestBuildAllSnapshots:
    """Tests for building snapshots for all servers from a flat tool list."""

    def test_groups_tools_by_server_id(self) -> None:
        from service.analytics.snapshots import build_all_snapshots

        tools = [
            {"tool_id": "s1::a", "server_id": "s1", "geo_score": {"total": 0.5}},
            {"tool_id": "s1::b", "server_id": "s1", "geo_score": {"total": 0.7}},
            {"tool_id": "s2::c", "server_id": "s2", "geo_score": {"total": 0.9}},
        ]
        snapshots = build_all_snapshots(tools)
        assert len(snapshots) == 2

        by_server = {s["server_id"]: s for s in snapshots}
        assert by_server["s1"]["tool_count"] == 2
        assert by_server["s2"]["tool_count"] == 1

    def test_empty_list(self) -> None:
        from service.analytics.snapshots import build_all_snapshots

        snapshots = build_all_snapshots([])
        assert snapshots == []

    def test_tools_without_server_id_uses_tool_id_prefix(self) -> None:
        """If server_id is missing, extract from tool_id (before ::)."""
        from service.analytics.snapshots import build_all_snapshots

        tools = [
            {"tool_id": "github::search", "geo_score": {"total": 0.6}},
            {"tool_id": "github::list", "geo_score": {"total": 0.8}},
        ]
        snapshots = build_all_snapshots(tools)
        assert len(snapshots) == 1
        assert snapshots[0]["server_id"] == "github"


# ============================================================
# 3. Search Simulation (offline rank lookup)
# ============================================================


class TestSimulateSearchRank:
    """Tests for offline search rank simulation."""

    def test_returns_rank_for_matching_tool(self) -> None:
        from service.analytics.simulation import simulate_search_rank

        precomputed_results = [
            {"tool_id": "srv::alpha", "score": 0.95},
            {"tool_id": "srv::beta", "score": 0.80},
            {"tool_id": "srv::gamma", "score": 0.60},
        ]
        rank = simulate_search_rank(
            tool_id="srv::beta",
            precomputed_results=precomputed_results,
        )
        assert rank == 2

    def test_returns_none_for_missing_tool(self) -> None:
        from service.analytics.simulation import simulate_search_rank

        precomputed_results = [
            {"tool_id": "srv::alpha", "score": 0.95},
            {"tool_id": "srv::beta", "score": 0.80},
        ]
        rank = simulate_search_rank(
            tool_id="srv::missing",
            precomputed_results=precomputed_results,
        )
        assert rank is None

    def test_rank_1_for_top_result(self) -> None:
        from service.analytics.simulation import simulate_search_rank

        precomputed_results = [
            {"tool_id": "srv::top", "score": 0.99},
            {"tool_id": "srv::second", "score": 0.50},
        ]
        rank = simulate_search_rank(
            tool_id="srv::top",
            precomputed_results=precomputed_results,
        )
        assert rank == 1

    def test_empty_results(self) -> None:
        from service.analytics.simulation import simulate_search_rank

        rank = simulate_search_rank(
            tool_id="srv::any",
            precomputed_results=[],
        )
        assert rank is None


class TestBuildSimulationReport:
    """Tests for building a multi-query simulation report for a tool."""

    def test_aggregates_across_queries(self) -> None:
        from service.analytics.simulation import build_simulation_report

        query_results = {
            "search repos on github": [
                {"tool_id": "github::search", "score": 0.9},
                {"tool_id": "gitlab::search", "score": 0.7},
            ],
            "list github issues": [
                {"tool_id": "github::list_issues", "score": 0.95},
                {"tool_id": "github::search", "score": 0.8},
            ],
            "unrelated query": [
                {"tool_id": "slack::send", "score": 0.9},
            ],
        }
        report = build_simulation_report(
            tool_id="github::search",
            query_results=query_results,
        )
        assert report["tool_id"] == "github::search"
        assert report["total_queries"] == 3
        assert report["appeared_in"] == 2
        assert report["rank_1_count"] == 1  # top in first query only
        assert report["avg_rank"] == pytest.approx(1.5, abs=1e-4)  # (1+2)/2

    def test_tool_not_in_any_results(self) -> None:
        from service.analytics.simulation import build_simulation_report

        query_results = {
            "q1": [{"tool_id": "other::tool", "score": 0.9}],
        }
        report = build_simulation_report(
            tool_id="missing::tool",
            query_results=query_results,
        )
        assert report["total_queries"] == 1
        assert report["appeared_in"] == 0
        assert report["rank_1_count"] == 0
        assert report["avg_rank"] is None

    def test_empty_query_results(self) -> None:
        from service.analytics.simulation import build_simulation_report

        report = build_simulation_report(
            tool_id="any::tool",
            query_results={},
        )
        assert report["total_queries"] == 0
        assert report["appeared_in"] == 0
        assert report["avg_rank"] is None


# ============================================================
# 4. SQL Migration contract test (004)
# ============================================================


class TestProviderSearchSimulationContract:
    """Verify migration 004 includes the search simulation view."""

    def test_migration_004_exists(self) -> None:
        from pathlib import Path

        migrations = list(Path("service/supabase/migrations").glob("004_*.sql"))
        assert len(migrations) == 1, "Expected exactly one 004_*.sql migration"

    def test_migration_004_contains_provider_search_simulations_view(self) -> None:
        from pathlib import Path

        migrations = list(Path("service/supabase/migrations").glob("004_*.sql"))
        sql = migrations[0].read_text()
        assert "provider_search_simulations" in sql
