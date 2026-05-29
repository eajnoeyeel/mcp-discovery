"""Canonical entity models — normalized, deduplicated, versioned."""

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, Field


class EntityStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    UNREACHABLE = "unreachable"
    SUPERSEDED = "superseded"
    QUARANTINED = "quarantined"


class FreshnessTier(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class CanonicalTool(BaseModel):
    """Normalized tool entity — the control-plane source of truth.

    Note: Unlike MCPTool, tool_id is NOT validated against server_id::tool_name
    format because canonical tools may originate from external sources (MCP-Zero,
    MCP-Atlas) whose IDs don't follow the :: convention until normalization.
    """

    tool_id: str
    server_id: str
    tool_name: str
    description: str | None = None
    input_schema: dict | None = None
    entity_status: EntityStatus = EntityStatus.ACTIVE
    content_hash: str | None = None
    source_updated_at: AwareDatetime | None = None
    indexed_at: AwareDatetime | None = None
    last_health_check_at: AwareDatetime | None = None


class CanonicalServer(BaseModel):
    """Normalized server entity."""

    server_id: str
    name: str
    description: str | None = None
    url: str | None = None
    tags: list[str] = Field(default_factory=list)
    entity_status: EntityStatus = EntityStatus.ACTIVE
    source_updated_at: AwareDatetime | None = None
    last_health_check_at: AwareDatetime | None = None
