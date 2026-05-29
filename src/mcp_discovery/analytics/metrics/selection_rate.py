"""Backward-compatibility shim — import from recommendation_rate instead.

This file will be removed after the next release cycle.
"""

from mcp_discovery.analytics.metrics.recommendation_rate import (  # noqa: F401
    RecommendationRateMetric,
    SelectionRateMetric,
)
