"""Tests for enrichment diff generator."""

from mcp_discovery.analytics.enrichment_diff import compute_enrichment_diff


class TestEnrichmentDiff:
    def test_basic_diff(self) -> None:
        diff = compute_enrichment_diff(
            raw_description="Search repositories on GitHub",
            enriched_text=(
                "search_repositories repo repository github Search GitHub repositories"
                " by topic, language, stars. Use when finding open-source projects."
            ),
            tool_name="search_repositories",
            parameter_names=["query", "language", "sort"],
        )
        assert diff.raw_description == "Search repositories on GitHub"
        assert diff.enriched_text is not None
        assert len(diff.added_keywords) > 0
        assert diff.raw_token_count > 0
        assert diff.enriched_token_count > 0

    def test_missing_params_detected(self) -> None:
        diff = compute_enrichment_diff(
            raw_description="Search repos",
            enriched_text="search_repositories query language Search repos by topic",
            tool_name="search_repositories",
            parameter_names=["query", "language", "sort"],
        )
        assert "sort" in diff.missing_in_raw

    def test_none_raw_description(self) -> None:
        diff = compute_enrichment_diff(
            raw_description=None,
            enriched_text="search repos",
            tool_name="search",
            parameter_names=[],
        )
        assert diff.raw_description is None
        assert diff.raw_token_count == 0

    def test_gap_dimensions(self) -> None:
        diff = compute_enrichment_diff(
            raw_description="Search repos",
            enriched_text=(
                "search_repositories query language Search repos by topic."
                " Use when looking for code repositories."
            ),
            tool_name="search_repositories",
            parameter_names=["query", "language"],
        )
        assert isinstance(diff.gap_dimensions, list)
