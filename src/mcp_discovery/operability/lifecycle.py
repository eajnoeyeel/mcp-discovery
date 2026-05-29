"""Tool lifecycle state machine — control-plane only. Query-plane must NOT import this."""

from __future__ import annotations

MIN_SUPPORT_DEFAULT = 20
STALE_THRESHOLD_DAYS = 90
QUARANTINE_SUCCESS_THRESHOLD = 0.1


class InvalidTransitionError(ValueError):
    """Raised when an invalid lifecycle transition is attempted."""


VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"active"},
    "active": {"unreachable", "stale", "quarantined", "deprecated"},
    "unreachable": {"active", "deprecated"},
    "stale": {"active", "deprecated"},
    "quarantined": {"active", "deprecated"},
    "deprecated": set(),  # terminal
}


def transition(current: str, target: str) -> str:
    """Validate and execute a lifecycle transition."""
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidTransitionError(f"{current} → {target} is not allowed")
    return target


def derive_status(
    *,
    call_count: int,
    success_rate: float | None,
    operational_freshness_days: int | None,
    deprecated: bool,
    min_support: int = MIN_SUPPORT_DEFAULT,
) -> str:
    """Derive tool status from operational stats. Called by control-plane batch job."""
    if deprecated:
        return "deprecated"
    if operational_freshness_days is not None and operational_freshness_days > STALE_THRESHOLD_DAYS:
        return "stale"
    if (
        call_count >= min_support
        and success_rate is not None
        and success_rate < QUARANTINE_SUCCESS_THRESHOLD
    ):
        return "quarantined"
    return "active"
