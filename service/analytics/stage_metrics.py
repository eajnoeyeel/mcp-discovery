"""Pydantic v2 model for query_logs.stage_metrics JSONB payload."""

from pydantic import BaseModel


class StageMetrics(BaseModel):
    source_path: str | None = None
    candidate_ms: float | None = None
    freshness_ms: float | None = None
    rerank_ms: float | None = None
    fallback_used: bool = False
    cold_cache: bool = False
