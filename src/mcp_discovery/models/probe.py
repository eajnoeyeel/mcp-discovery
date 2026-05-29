"""Pydantic models for the MCP probe + reconcile infrastructure (ADR-0018).

Five types exported from this module:
  - ProbeErrorKind   — error classification enum
  - TransportSpec    — base transport descriptor (discriminated union in data/transport_spec.py)
  - RawToolInventory — raw tools/list response captured before MCPTool strict validation
  - ProbeResult      — outcome of probing a single server
  - ReconcilePlan    — full GT reconcile plan produced by gt_reconciler
"""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProbeErrorKind(str, Enum):
    """Classification of probe failures.

    Values must be stable — reconcile plans reference them by name.
    """

    TRANSPORT_UNSUPPORTED = "TRANSPORT_UNSUPPORTED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    TIMEOUT = "TIMEOUT"
    HANDSHAKE_FAILED = "HANDSHAKE_FAILED"
    PROTOCOL_VERSION_MISMATCH = "PROTOCOL_VERSION_MISMATCH"
    UNREACHABLE = "UNREACHABLE"
    SCHEMA_INVALID = "SCHEMA_INVALID"


class TransportSpec(BaseModel):
    """Base transport descriptor.

    The discriminated union (StdioTransportSpec / HttpTransportSpec / ScriptTransportSpec)
    is defined in src/mcp_discovery/data/transport_spec.py so that the YAML loader and
    Pydantic discriminated-union machinery live close to the data artefacts.

    This base class is imported by ProbeResult and pool_prober to avoid a circular
    dependency between models/ and data/.
    """

    transport: str = Field(..., description="Transport type discriminator (stdio | http | script)")
    server_id: str = Field(..., description="Canonical server_id for this transport spec")

    model_config = {"extra": "forbid"}


class RawToolInventory(BaseModel):
    """Raw tools/list response captured directly from an MCP server.

    Uses extra='allow' so that fields not yet in MCPTool (e.g. experimental annotations,
    custom extensions) are preserved in the audit snapshot without validation errors.
    The strict MCPTool validator is applied downstream by MCPDirectConnector.parse_tools().
    """

    server_id: str = Field(..., description="Server that produced this inventory")
    tools: list[dict[str, Any]] = Field(
        default_factory=list, description="Raw tool objects from tools/list"
    )
    captured_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        description="UTC timestamp when this snapshot was captured",
    )
    protocol_version: str | None = Field(
        default=None,
        description="MCP protocol version string reported by the server during initialize",
    )

    model_config = {"extra": "allow"}


class ProbeResult(BaseModel):
    """Outcome of probing a single MCP server.

    A successful probe captures a RawToolInventory; a failed probe captures the error kind
    and an optional human-readable message. Both outcomes include the content-hash of the
    spec that was used, enabling cache look-up and audit chain linkage.
    """

    server_id: str = Field(..., description="Server that was probed")
    success: bool = Field(..., description="True if tools/list was retrieved without error")
    spec_hash: str = Field(
        ...,
        description=(
            "SHA-256 hex of spec.model_dump_json() — links result to exact transport config"
        ),
    )
    probed_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        description="UTC timestamp when the probe was executed",
    )

    # Success path
    inventory: RawToolInventory | None = Field(
        default=None,
        description="Raw tool inventory — present iff success=True",
    )
    server_offered_protocol_version: str | None = Field(
        default=None,
        description="MCP protocol version string from the server's initialize response (AC19)",
    )

    # Failure path
    error_kind: ProbeErrorKind | None = Field(
        default=None,
        description="Failure classification — present iff success=False",
    )
    error_message: str | None = Field(
        default=None,
        description="Human-readable error detail — never contains secrets",
    )

    model_config = {"extra": "forbid"}


class ReconcileAction(BaseModel):
    """A single GT row transformation proposed by the reconciler."""

    rule: Literal["R1", "R2", "R3", "R4", "R5"] = Field(
        ...,
        description=(
            "Reconcile rule that produced this action"
            " (R1=exact, R2=manual, R3=fuzzy, R4=server_renamed, R5=drop)"
        ),
    )
    query_id: str = Field(..., description="GT query_id being acted on")
    old_tool_id: str = Field(..., description="Current correct_tool_id in the GT row")
    new_tool_id: str | None = Field(
        default=None,
        description="Replacement tool_id (None for R5 drop actions)",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fuzzy match confidence for R3 actions; None for exact/manual/drop",
    )
    notes: str | None = Field(default=None, description="Audit note appended to GT row")
    probe_sha: str | None = Field(
        default=None,
        description="spec_hash of the ProbeResult that informed this action",
    )

    model_config = {"extra": "forbid"}


class ReconcilePlan(BaseModel):
    """Full GT reconcile plan produced by gt_reconciler.

    schema_version='1' is a Literal — downstream consumers can gate on it (AC17).
    The plan is immutable once produced; mutations generate a new plan.
    """

    schema_version: Literal["1"] = Field(
        default="1",
        description="Plan schema version — bump when layout changes (AC17)",
    )
    plan_hash: str = Field(
        ...,
        description="SHA-256 hex of the serialised action list — stable identifier for journal entries",  # noqa: E501
    )
    created_at: datetime.datetime = Field(
        default_factory=datetime.datetime.utcnow,
        description="UTC timestamp when the plan was produced",
    )
    actions: list[ReconcileAction] = Field(
        default_factory=list,
        description="Ordered list of reconcile actions (R2→R1→R4→R3→R5 ordering preserved by reconciler)",  # noqa: E501
    )
    review_queue: list[ReconcileAction] = Field(
        default_factory=list,
        description="R3 fuzzy matches in 0.80–0.88 band requiring human review before application",
    )
    probe_results: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping server_id → ProbeResult.spec_hash for audit traceability",
    )

    model_config = {"extra": "forbid"}
