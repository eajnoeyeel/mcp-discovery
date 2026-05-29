"""Tests for canonical data contract types."""

from datetime import datetime, timezone

from mcp_discovery.models.canonical import CanonicalTool, EntityStatus, FreshnessTier


def test_canonical_tool_defaults():
    tool = CanonicalTool(
        tool_id="github::search_repos",
        server_id="github",
        tool_name="search_repos",
        description="Search repos",
    )
    assert tool.entity_status == EntityStatus.ACTIVE
    assert tool.content_hash is None
    assert tool.source_updated_at is None
    assert tool.indexed_at is None


def test_entity_status_values():
    assert EntityStatus.ACTIVE == "active"
    assert EntityStatus.DEPRECATED == "deprecated"
    assert EntityStatus.UNREACHABLE == "unreachable"
    assert EntityStatus.SUPERSEDED == "superseded"
    assert EntityStatus.QUARANTINED == "quarantined"


def test_freshness_tier_values():
    assert FreshnessTier.FRESH == "fresh"
    assert FreshnessTier.STALE == "stale"
    assert FreshnessTier.UNKNOWN == "unknown"


def test_canonical_tool_accepts_aware_datetime():
    """CanonicalTool accepts timezone-aware datetimes."""
    now = datetime.now(timezone.utc)
    tool = CanonicalTool(
        tool_id="github::search_repos",
        server_id="github",
        tool_name="search_repos",
        description="Search repos",
        indexed_at=now,
    )
    assert tool.indexed_at == now
    assert tool.indexed_at.tzinfo is not None
