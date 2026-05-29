"""Tests for DescriptionQualityMetric (Feature 2)."""

from mcp_discovery.analytics.metrics.base import MetricContext
from mcp_discovery.analytics.metrics.description_quality import DescriptionQualityMetric


class TestDescriptionQualityMetric:
    def test_compute_with_raw_and_enriched(self) -> None:
        metric = DescriptionQualityMetric()
        ctx = MetricContext(
            tool_id="github::search",
            server_id="github",
            raw_description="Search repositories on GitHub",
            enriched_text=(
                "search_repositories repo repository github Search GitHub"
                " repositories by topic, language, stars. Use when finding"
                " open-source projects."
            ),
            input_schema={"properties": {"query": {}, "language": {}, "sort": {}}},
        )
        result = metric.compute(ctx)

        assert "geo_score" in result.value
        assert "enrichment_diff" in result.value
        assert "token_stats" in result.value
        assert result.value["geo_score"]["total"] >= 0.0
        assert result.value["token_stats"]["raw_tokens"] > 0

    def test_compute_without_enrichment(self) -> None:
        metric = DescriptionQualityMetric()
        ctx = MetricContext(
            tool_id="t1",
            server_id="s1",
            raw_description="A simple tool",
            enriched_text=None,
        )
        result = metric.compute(ctx)
        assert result.value["enrichment_diff"] is None
        assert result.value["geo_score"]["total"] >= 0.0

    def test_compute_none_description(self) -> None:
        metric = DescriptionQualityMetric()
        ctx = MetricContext(tool_id="t1", server_id="s1")
        result = metric.compute(ctx)
        assert result.value["geo_score"]["total"] == 0.0
