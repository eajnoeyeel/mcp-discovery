"""Tests for DescriptionGEOScorer and build_confusion_matrix (Phase 9 — Task 9.2)."""

import pytest

from mcp_discovery.analytics.aggregator import ToolStats
from mcp_discovery.analytics.confusion_matrix import ConfusionEntry, build_confusion_matrix
from mcp_discovery.analytics.geo_score import DescriptionGEOScorer, GEOScore

# ===========================================================================
# GEOScore model
# ===========================================================================


class TestGEOScore:
    def test_has_all_dimensions(self) -> None:
        score = GEOScore(
            clarity=0.8,
            disambiguation=0.5,
            parameter_coverage=0.6,
            boundary=0.4,
            stats=0.7,
            precision=0.9,
            total=0.65,
        )
        assert score.clarity == 0.8
        assert score.disambiguation == 0.5
        assert score.parameter_coverage == 0.6
        assert score.boundary == 0.4
        assert score.stats == 0.7
        assert score.precision == 0.9
        assert score.total == 0.65

    def test_all_dimensions_in_zero_one_range(self) -> None:
        score = GEOScore(
            clarity=0.0,
            disambiguation=1.0,
            parameter_coverage=0.5,
            boundary=0.5,
            stats=0.5,
            precision=0.5,
            total=0.5,
        )
        for field in [
            "clarity",
            "disambiguation",
            "parameter_coverage",
            "boundary",
            "stats",
            "precision",
            "total",
        ]:
            val = getattr(score, field)
            assert 0.0 <= val <= 1.0, f"{field}={val} out of range"


# ===========================================================================
# DescriptionGEOScorer
# ===========================================================================


class TestDescriptionGEOScorer:
    @pytest.fixture()
    def scorer(self) -> DescriptionGEOScorer:
        return DescriptionGEOScorer()

    # --- Vague description: total < 0.4 ---
    def test_vague_description_low_score(self, scorer: DescriptionGEOScorer) -> None:
        result = scorer.score("A tool for doing things.")
        assert result.total < 0.4

    def test_vague_description_another(self, scorer: DescriptionGEOScorer) -> None:
        result = scorer.score("This helps with stuff.")
        assert result.total < 0.4

    # --- Specific description: total > 0.7 ---
    def test_specific_description_high_score(self, scorer: DescriptionGEOScorer) -> None:
        desc = (
            "Search for academic papers on Semantic Scholar by keyword, author, or DOI. "
            "Returns up to 100 results per query with title, abstract, citation count, "
            "and publication year. Accepts parameters: query (string, required), "
            "limit (int, 1-100), fields (list). "
            "Does NOT perform full-text search or access paywalled content. "
            "Unlike Google Scholar, focuses on computer science and biomedical literature. "
            "Covers 200M+ papers with 95% recall on CS papers since 2000."
        )
        result = scorer.score(desc)
        assert result.total > 0.7

    def test_specific_description_with_technical_terms(self, scorer: DescriptionGEOScorer) -> None:
        desc = (
            "Execute SQL queries against a PostgreSQL database via the pg_catalog protocol. "
            "Accepts parameters: query (string), timeout_ms (int, default 5000). "
            "Supports SELECT, INSERT, UPDATE, DELETE with parameterized queries. "
            "Does NOT support DDL operations (CREATE, DROP, ALTER). "
            "Unlike direct psql access, enforces row-level security policies. "
            "Handles up to 10,000 rows per response with 99.9% uptime SLA."
        )
        result = scorer.score(desc)
        assert result.total > 0.7

    # --- Individual dimensions ---
    def test_clarity_high_for_clear_first_sentence(self, scorer: DescriptionGEOScorer) -> None:
        desc = "Search for academic papers by keyword and author on Semantic Scholar."
        result = scorer.score(desc)
        assert result.clarity > 0.5

    def test_clarity_low_for_vague_first_sentence(self, scorer: DescriptionGEOScorer) -> None:
        desc = "A tool."
        result = scorer.score(desc)
        assert result.clarity < 0.5

    def test_disambiguation_with_not_keywords(self, scorer: DescriptionGEOScorer) -> None:
        desc = "Does NOT handle binary files. Unlike grep, supports semantic search."
        result = scorer.score(desc)
        assert result.disambiguation > 0.5

    def test_disambiguation_absent(self, scorer: DescriptionGEOScorer) -> None:
        desc = "Searches for files in a directory."
        result = scorer.score(desc)
        assert result.disambiguation < 0.3

    def test_parameter_coverage_present(self, scorer: DescriptionGEOScorer) -> None:
        desc = "Accepts parameters: query (string, required), limit (int, 1-100)."
        result = scorer.score(desc)
        assert result.parameter_coverage > 0.5

    def test_parameter_coverage_absent(self, scorer: DescriptionGEOScorer) -> None:
        desc = "Searches for stuff."
        result = scorer.score(desc)
        assert result.parameter_coverage < 0.3

    def test_boundary_with_not_statements(self, scorer: DescriptionGEOScorer) -> None:
        desc = "Does NOT support file uploads. Cannot handle images larger than 10MB."
        result = scorer.score(desc)
        assert result.boundary > 0.5

    def test_stats_with_numbers(self, scorer: DescriptionGEOScorer) -> None:
        desc = "Covers 200M+ papers with 95% recall. Returns up to 100 results."
        result = scorer.score(desc)
        assert result.stats > 0.5

    def test_stats_without_numbers(self, scorer: DescriptionGEOScorer) -> None:
        desc = "Searches for papers."
        result = scorer.score(desc)
        assert result.stats < 0.3

    def test_precision_with_technical_terms(self, scorer: DescriptionGEOScorer) -> None:
        desc = "Queries via REST API using OAuth 2.0 with JSON-LD responses."
        result = scorer.score(desc)
        assert result.precision > 0.5

    def test_precision_without_technical_terms(self, scorer: DescriptionGEOScorer) -> None:
        desc = "Does some things with data."
        result = scorer.score(desc)
        assert result.precision < 0.3

    # --- total = equal weight 1/6 ---
    def test_total_is_mean_of_six_dimensions(self, scorer: DescriptionGEOScorer) -> None:
        desc = (
            "Search academic papers on Semantic Scholar by keyword. "
            "Accepts parameters: query (string). "
            "Does NOT access paywalled content. Unlike Google Scholar, CS-focused. "
            "Covers 200M+ papers with 95% recall. Uses REST API with DOI resolution."
        )
        result = scorer.score(desc)
        expected_total = (
            result.clarity
            + result.disambiguation
            + result.parameter_coverage
            + result.boundary
            + result.stats
            + result.precision
        ) / 6
        assert result.total == pytest.approx(expected_total, abs=1e-6)

    # --- Edge cases ---
    def test_empty_description(self, scorer: DescriptionGEOScorer) -> None:
        result = scorer.score("")
        assert result.total == 0.0

    def test_none_safe(self, scorer: DescriptionGEOScorer) -> None:
        """score() should handle None gracefully."""
        result = scorer.score(None)  # type: ignore[arg-type]
        assert result.total == 0.0


# ===========================================================================
# Confusion Matrix
# ===========================================================================


class TestBuildConfusionMatrix:
    def test_empty_stats(self) -> None:
        result = build_confusion_matrix({})
        assert result == []

    def test_single_tool(self) -> None:
        stats = {
            "A": ToolStats(tool_id="A", selection_count=5, runner_up_count=2, lost_to={"B": 2}),
        }
        result = build_confusion_matrix(stats)
        assert len(result) == 1
        entry = result[0]
        assert entry.tool_id == "A"
        assert entry.selections == 5
        assert entry.runner_up == 2
        assert entry.win_rate == pytest.approx(5 / 7)
        assert entry.lost_to_top5 == [("B", 2)]

    def test_multiple_tools_sorted_by_selections(self) -> None:
        stats = {
            "A": ToolStats(tool_id="A", selection_count=2, runner_up_count=0, lost_to={}),
            "B": ToolStats(tool_id="B", selection_count=10, runner_up_count=1, lost_to={"A": 1}),
            "C": ToolStats(
                tool_id="C", selection_count=5, runner_up_count=3, lost_to={"B": 2, "A": 1}
            ),
        }
        result = build_confusion_matrix(stats)
        # Sorted descending by selections
        assert result[0].tool_id == "B"
        assert result[1].tool_id == "C"
        assert result[2].tool_id == "A"

    def test_lost_to_top5_limited(self) -> None:
        lost_to = {f"tool_{i}": 10 - i for i in range(8)}
        stats = {
            "A": ToolStats(tool_id="A", selection_count=1, runner_up_count=20, lost_to=lost_to),
        }
        result = build_confusion_matrix(stats)
        assert len(result[0].lost_to_top5) == 5
        # Sorted by count descending
        counts = [c for _, c in result[0].lost_to_top5]
        assert counts == sorted(counts, reverse=True)

    def test_confusion_entry_fields(self) -> None:
        entry = ConfusionEntry(
            tool_id="X",
            selections=10,
            runner_up=5,
            win_rate=0.667,
            lost_to_top5=[("Y", 3), ("Z", 2)],
        )
        assert entry.tool_id == "X"
        assert entry.selections == 10
        assert entry.runner_up == 5
        assert entry.win_rate == 0.667
        assert entry.lost_to_top5 == [("Y", 3), ("Z", 2)]
