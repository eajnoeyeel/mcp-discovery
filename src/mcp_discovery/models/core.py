"""Core data models for MCP Discovery Platform."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mcp_discovery.operability.models import ToolOperabilityEnrichment  # noqa: F401

from pydantic import (
    BaseModel,
    Field,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)

TOOL_ID_SEPARATOR = "::"

SourcePathLiteral = Literal[
    "semantic",
    "hybrid_semantic",
    "dense_only_degraded",
    "lexical_fallback",
    "mixed",
    "freshness",
]


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Ambiguity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Category(StrEnum):
    SEARCH = "search"
    CODE = "code"
    DATABASE = "database"
    COMMUNICATION = "communication"
    PRODUCTIVITY = "productivity"
    SCIENCE = "science"
    FINANCE = "finance"
    GENERAL = "general"


class MCPServerSummary(BaseModel):
    """Smithery list endpoint summary — no tools."""

    qualified_name: str
    display_name: str
    description: str | None = None
    use_count: int = 0
    is_verified: bool = False
    is_deployed: bool = False


class MCPTool(BaseModel):
    """A single MCP tool with validated tool_id."""

    server_id: str
    tool_name: str
    tool_id: str
    description: str | None = None
    selection_description: str | None = None
    input_schema: dict | None = None

    @computed_field
    @property
    def parameter_names(self) -> list[str]:
        if not self.input_schema:
            return []
        props = self.input_schema.get("properties", {})
        return list(props.keys())

    @field_validator("tool_id")
    @classmethod
    def validate_tool_id(cls, v: str, info: ValidationInfo) -> str:
        server_id = info.data.get("server_id", "")
        tool_name = info.data.get("tool_name", "")
        expected = f"{server_id}{TOOL_ID_SEPARATOR}{tool_name}"
        if v != expected:
            raise ValueError(f"tool_id must be '{expected}', got '{v}'")
        return v


class MCPServer(BaseModel):
    """MCP server with its tools."""

    server_id: str
    name: str
    description: str | None = None
    homepage: str | None = None
    tools: list[MCPTool] = []


class ScoreBreakdown(BaseModel):
    """Composite score decomposition for transparency (PD7).

    MLP: quality=0.0, boost=0.0, trust=0.0, operability=0.0 (relevance-only).
    Phase 2: quality and boost activated after data accumulation.
    Phase 2+: trust and operability activated after provider telemetry.
    """

    relevance: float = Field(
        ..., description="Retrieval relevance score (embedding cosine similarity)"
    )
    quality: float = Field(0.0, description="Description quality score (GEO 6D)")
    boost: float = Field(0.0, description="Provider boost score")
    trust: float = Field(0.0, description="Provider trust score (Phase 2)")
    operability: float = Field(0.0, description="Tool operability score (Phase 2)")
    dense_score: float | None = Field(None, description="Dense embedding score (hybrid path)")
    sparse_score: float | None = Field(None, description="Sparse/BM25 score (hybrid path)")
    rrf_score: float | None = Field(None, description="Reciprocal Rank Fusion score (hybrid path)")


class SearchResult(BaseModel):
    """A single search result from the pipeline."""

    tool: MCPTool
    score: float
    rank: int
    reason: str | None = None
    # PD1: LLM clients need input_schema for parameterization
    input_schema: dict | None = None
    # PD7: Composite scoring transparency
    score_breakdown: ScoreBreakdown | None = None
    is_boosted: bool = False
    source_path: SourcePathLiteral = "semantic"
    # Operability enrichment (optional, backward compatible)
    operability: "ToolOperabilityEnrichment | None" = None
    retrieval_score: float | None = None  # preserved original retrieval score before score merge

    @model_validator(mode="after")
    def sync_input_schema_from_tool(self) -> "SearchResult":
        if self.input_schema is None and self.tool.input_schema is not None:
            self.input_schema = self.tool.input_schema
        return self


class FindBestToolRequest(BaseModel):
    """API request for tool discovery."""

    query: str
    top_k: int = Field(default=3, ge=1)
    strategy: str = "sequential"


class FindBestToolResponse(BaseModel):
    """API response for tool discovery."""

    query: str
    results: list[SearchResult]
    confidence: float
    disambiguation_needed: bool
    strategy_used: str
    latency_ms: float
    degraded: bool = False
    source_path: SourcePathLiteral = "semantic"


class GroundTruthEntry(BaseModel):
    """Ground Truth entry — a single (query, correct_tool) pair for evaluation.

    Full Phase 4 schema with enums and cross-field validation.
    """

    # Identity
    query_id: str = Field(description="Unique ID, e.g. 'gt-search-001'")
    query: str = Field(description="Natural language query")

    # Ground truth labels
    correct_server_id: str = Field(description="Correct MCP server ID")
    correct_tool_id: str = Field(description="Correct tool ID (server_id::tool_name)")

    # Classification
    difficulty: Difficulty
    category: Category
    ambiguity: Ambiguity

    # Provenance
    source: Literal[
        "manual_seed",
        "llm_synthetic",
        "llm_verified",
        "external_mcp_atlas",
        "external_mcp_zero",
    ] = Field(description="Origin of this ground truth entry")
    manually_verified: bool = False
    author: str = Field(description="Author ID or model name")
    created_at: str = Field(description="ISO 8601 date")

    # ADR-0012: task type and lineage
    task_type: Literal["single_step"] = Field(
        default="single_step", description="Always single_step (ADR-0012)"
    )
    origin_task_id: str | None = Field(
        default=None, description="MCP-Atlas original task ID (null for seed/synthetic)"
    )
    step_index: int | None = Field(
        default=None,
        description="0-indexed step position in original task (null for seed/synthetic)",
    )

    # Optional — graded relevance for NDCG@5
    alternative_tools: list[str] | None = None
    notes: str | None = None

    @field_validator("correct_tool_id")
    @classmethod
    def validate_tool_id_matches_server(cls, v: str, info: ValidationInfo) -> str:
        server_id = info.data.get("correct_server_id", "")
        if server_id and not v.startswith(f"{server_id}{TOOL_ID_SEPARATOR}"):
            raise ValueError(
                f"correct_tool_id '{v}' must start with '{server_id}{TOOL_ID_SEPARATOR}'"
            )
        return v

    @model_validator(mode="after")
    def validate_cross_field_rules(self) -> "GroundTruthEntry":
        # hard difficulty requires non-low ambiguity
        if self.difficulty == Difficulty.HARD and self.ambiguity == Ambiguity.LOW:
            raise ValueError("hard difficulty requires ambiguity 'medium' or 'high', got 'low'")
        # medium/high ambiguity requires alternative_tools
        if self.ambiguity in (Ambiguity.MEDIUM, Ambiguity.HIGH):
            if not self.alternative_tools:
                raise ValueError(
                    f"ambiguity '{self.ambiguity.value}' requires non-empty alternative_tools"
                )
        # manual_seed must be manually verified
        if self.source == "manual_seed" and not self.manually_verified:
            raise ValueError("source='manual_seed' entries must have manually_verified=True")
        # external_mcp_atlas (human-authored) must be manually verified
        if self.source == "external_mcp_atlas" and not self.manually_verified:
            raise ValueError("source='external_mcp_atlas' entries must have manually_verified=True")
        # external_mcp_atlas requires lineage fields (ADR-0012)
        if self.source == "external_mcp_atlas":
            if self.origin_task_id is None or self.step_index is None:
                raise ValueError(
                    "source='external_mcp_atlas' entries must have origin_task_id and step_index"
                )
        return self


# Resolve forward references after all models are defined.
# Import here (not at top) to avoid circular imports; operability.models does not import core.
from mcp_discovery.operability.models import (  # noqa: E402  # isort: skip
    ToolOperabilityEnrichment as _ToolOperabilityEnrichment,
)

SearchResult.model_rebuild(
    _types_namespace={"ToolOperabilityEnrichment": _ToolOperabilityEnrichment}
)
