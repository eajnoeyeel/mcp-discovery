"""Enrichment diff — compares raw vs enriched description for Provider insight.

Shows what the enrichment pipeline added, what's missing in the raw description,
and which GEO dimensions have gaps.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from mcp_discovery.analytics.geo_score import DescriptionGEOScorer, GEOScore
from mcp_discovery.analytics.token_counter import count_tokens


class EnrichmentDiff(BaseModel):
    """Comparison between raw and enriched description."""

    tool_id: str
    raw_description: str | None
    enriched_text: str | None
    raw_geo: GEOScore
    enriched_geo: GEOScore
    raw_token_count: int
    enriched_token_count: int
    added_keywords: list[str] = Field(default_factory=list)
    missing_in_raw: list[str] = Field(
        default_factory=list,
        description="Parameter names present in schema but absent from raw description",
    )
    gap_dimensions: list[str] = Field(
        default_factory=list,
        description="GEO dimensions where enriched > raw by 0.2+",
    )


_GEO_SCORER = DescriptionGEOScorer()
_GEO_DIM_THRESHOLD = 0.2


def compute_enrichment_diff(
    raw_description: str | None,
    enriched_text: str | None,
    tool_name: str,
    parameter_names: list[str],
    tool_id: str = "",
) -> EnrichmentDiff:
    """Compare raw vs enriched description and identify gaps."""
    raw_geo = _GEO_SCORER.score(raw_description)
    enriched_geo = _GEO_SCORER.score(enriched_text)

    raw_words = set(re.findall(r"\w+", (raw_description or "").lower()))
    enriched_words = set(re.findall(r"\w+", (enriched_text or "").lower()))
    added = sorted(enriched_words - raw_words)

    missing = [p for p in parameter_names if p.lower() not in raw_words and len(p) > 1]

    gaps: list[str] = []
    for dim in (
        "clarity",
        "disambiguation",
        "parameter_coverage",
        "boundary",
        "stats",
        "precision",
    ):
        raw_val = getattr(raw_geo, dim)
        enr_val = getattr(enriched_geo, dim)
        if enr_val - raw_val >= _GEO_DIM_THRESHOLD:
            gaps.append(dim)

    return EnrichmentDiff(
        tool_id=tool_id,
        raw_description=raw_description,
        enriched_text=enriched_text,
        raw_geo=raw_geo,
        enriched_geo=enriched_geo,
        raw_token_count=count_tokens(raw_description),
        enriched_token_count=count_tokens(enriched_text),
        added_keywords=added[:20],
        missing_in_raw=missing,
        gap_dimensions=gaps,
    )
