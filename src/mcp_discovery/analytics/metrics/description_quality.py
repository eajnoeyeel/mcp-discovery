"""Feature 2: Description quality — GEO score + enrichment diff + token efficiency."""

from __future__ import annotations

from mcp_discovery.analytics.enrichment_diff import compute_enrichment_diff
from mcp_discovery.analytics.geo_score import DescriptionGEOScorer
from mcp_discovery.analytics.metrics.base import MetricContext, MetricResult, ProviderMetric
from mcp_discovery.analytics.token_counter import TokenStats

_SCORER = DescriptionGEOScorer()


class DescriptionQualityMetric(ProviderMetric):
    """GEO score summary + enrichment diff detail + token efficiency."""

    @property
    def name(self) -> str:
        return "description_quality"

    def compute(self, context: MetricContext) -> MetricResult:
        tool_id = context.tool_id
        raw = context.raw_description
        enriched = context.enriched_text
        schema = context.input_schema

        geo = _SCORER.score(raw)
        token_stats = TokenStats.from_descriptions(raw=raw, enriched=enriched)

        diff_data = None
        if enriched:
            param_names: list[str] = []
            if schema and "properties" in schema:
                param_names = list(schema["properties"].keys())
            tool_name = tool_id.split("::")[-1] if "::" in tool_id else tool_id
            diff = compute_enrichment_diff(
                raw_description=raw,
                enriched_text=enriched,
                tool_name=tool_name,
                parameter_names=param_names,
                tool_id=tool_id,
            )
            diff_data = {
                "added_keywords": diff.added_keywords[:10],
                "missing_in_raw": diff.missing_in_raw,
                "gap_dimensions": diff.gap_dimensions,
                "enriched_geo_total": diff.enriched_geo.total,
            }

        return MetricResult(
            metric_name=self.name,
            value={
                "geo_score": {
                    "clarity": geo.clarity,
                    "disambiguation": geo.disambiguation,
                    "parameter_coverage": geo.parameter_coverage,
                    "boundary": geo.boundary,
                    "stats": geo.stats,
                    "precision": geo.precision,
                    "total": geo.total,
                },
                "token_stats": {
                    "raw_tokens": token_stats.raw_tokens,
                    "enriched_tokens": token_stats.enriched_tokens,
                    "ratio": token_stats.ratio,
                },
                "enrichment_diff": diff_data,
            },
        )
