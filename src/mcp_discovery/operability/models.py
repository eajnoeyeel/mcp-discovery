"""Operability data models — control-plane artifacts read by query-plane."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, computed_field


class FreshnessTriple(BaseModel):
    """Three independent freshness dimensions."""

    source_updated_at: datetime | None = None
    indexed_at: datetime | None = None
    last_successful_call_at: datetime | None = None

    @computed_field
    @property
    def source_freshness_days(self) -> int | None:
        if self.source_updated_at is None:
            return None
        delta = (
            datetime.now(timezone.utc) - self.source_updated_at.replace(tzinfo=timezone.utc)
            if self.source_updated_at.tzinfo is None
            else datetime.now(timezone.utc) - self.source_updated_at
        )
        return max(0, delta.days)

    @computed_field
    @property
    def index_freshness_days(self) -> int | None:
        if self.indexed_at is None:
            return None
        delta = datetime.now(timezone.utc) - (
            self.indexed_at.replace(tzinfo=timezone.utc)
            if self.indexed_at.tzinfo is None
            else self.indexed_at
        )
        return max(0, delta.days)

    @computed_field
    @property
    def operational_freshness_days(self) -> int | None:
        if self.last_successful_call_at is None:
            return None
        delta = datetime.now(timezone.utc) - (
            self.last_successful_call_at.replace(tzinfo=timezone.utc)
            if self.last_successful_call_at.tzinfo is None
            else self.last_successful_call_at
        )
        return max(0, delta.days)


class ToolOperabilitySnapshot(BaseModel):
    """Precomputed operability snapshot. Read-only in query-plane."""

    tool_id: str
    server_id: str
    status: Literal["pending", "active", "quarantined", "unreachable", "deprecated", "stale"] = (
        "active"
    )

    call_count: int = 0
    call_count_7d: int = 0
    success_rate: float | None = None
    success_rate_7d: float | None = None
    timeout_rate: float | None = None
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None

    freshness: FreshnessTriple = Field(default_factory=FreshnessTriple)

    min_support: int = 20
    operability_score: float | None = None
    boost: float = 0.0

    snapshot_version: int = 1
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @computed_field
    @property
    def cold_start(self) -> bool:
        return self.call_count < self.min_support


class ToolOperabilityEnrichment(BaseModel):
    """Lightweight operability metadata attached to search results."""

    status: str
    cold_start: bool
    success_rate: float | None = None
    avg_latency_ms: float | None = None
    freshness: FreshnessTriple | None = None
    operability_grade: Literal["A", "B", "C", "D", "F"] | None = None


def _compute_grade(score: float) -> Literal["A", "B", "C", "D", "F"]:
    if score >= 0.9:
        return "A"
    if score >= 0.7:
        return "B"
    if score >= 0.5:
        return "C"
    if score >= 0.3:
        return "D"
    return "F"


def compute_operability_float(
    *,
    success_rate: float | None,
    avg_latency_ms: float | None,
    timeout_rate: float | None,
) -> float:
    """Compress operability into a single float [0.0, 1.0]."""
    if success_rate is None:
        return 0.5  # cold-start neutral
    sr = success_rate
    latency_norm = max(0.0, 1.0 - (avg_latency_ms or 0) / 10_000)
    timeout_penalty = max(0.0, 1.0 - (timeout_rate or 0) * 5)
    return round(0.50 * sr + 0.30 * latency_norm + 0.20 * timeout_penalty, 4)


def build_enrichment(snap: ToolOperabilitySnapshot | None) -> ToolOperabilityEnrichment | None:
    """Build lightweight enrichment from a full snapshot."""
    if snap is None:
        return None
    op_score = compute_operability_float(
        success_rate=snap.success_rate,
        avg_latency_ms=snap.avg_latency_ms,
        timeout_rate=snap.timeout_rate,
    )
    return ToolOperabilityEnrichment(
        status=snap.status,
        cold_start=snap.cold_start,
        success_rate=snap.success_rate,
        avg_latency_ms=snap.avg_latency_ms,
        freshness=snap.freshness,
        operability_grade=_compute_grade(op_score),
    )
