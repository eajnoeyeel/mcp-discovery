"""Shared request contracts for MLP services."""

from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

MCPTransportType = Literal["stateless_http", "streamable_http", "sse", "stdio"]
UpstreamAuthType = Literal[
    "none",
    "bearer",
    "api_key_header",
    "custom_headers",
    "oauth_session",
]
ExecuteStatus = Literal[
    "ok",
    "auth_required",
    "auth_revoked",
    "upstream_auth_failed",
    "execution_failed",
]
ProviderAuthKind = Literal["oauth"]
ScopeMode = Literal["default", "override"]
ConnectionStatus = Literal["active", "expired", "revoked"]
TokenStorageMode = Literal["refreshable", "session_only"]


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=3, ge=1)
    client_id: str | None = None


class IndexRequest(BaseModel):
    server_id: str


class ExecuteRequest(BaseModel):
    tool_id: str
    params: dict = Field(default_factory=dict)


class UpstreamAuthConfig(BaseModel):
    """Provider MCP upstream auth metadata used only during execution."""

    auth_type: UpstreamAuthType = "none"
    bearer_token: str | None = None
    api_key_header_name: str | None = None
    api_key: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    oauth_token_endpoint: str | None = None
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    oauth_refresh_token: str | None = None
    oauth_scope: str | None = None


class AuthRequiredPayload(BaseModel):
    """Delegated OAuth details needed to resume a blocked execution."""

    provider: str
    required_scopes: list[str] = Field(default_factory=list)
    oauth_url: str
    retry_token: str
    pending_execution_id: str | None = None
    resume_token: str | None = None
    resume_strategy: str | None = None
    message: str | None = None


class ProviderAuthRequirement(BaseModel):
    """Per-tool/provider auth requirement surfaced to execution clients."""

    provider: str
    auth_kind: ProviderAuthKind = "oauth"
    required_scopes: list[str] = Field(default_factory=list)
    scope_mode: ScopeMode = "default"


class RegisterClientAuthRequirement(BaseModel):
    """Delegated client-auth metadata accepted during server registration."""

    provider_key: str
    auth_kind: ProviderAuthKind = "oauth"
    required_scopes: list[str] = Field(default_factory=list)
    scope_mode: ScopeMode = "default"


class UserProviderConnection(BaseModel):
    """Normalized user/provider OAuth connection metadata."""

    id: str
    user_id: str
    provider_key: str
    provider_account_id: str | None = None
    granted_scopes: list[str] = Field(default_factory=list)
    scope_fingerprint: str
    status: ConnectionStatus = "active"
    token_storage_mode: TokenStorageMode = "refreshable"


class ToolContract(BaseModel):
    """Metadata fetched from Supabase for a registered tool."""

    tool_id: str
    server_id: str
    tool_name: str
    url: str
    input_schema: dict | None = None
    upstream_auth: UpstreamAuthConfig = Field(default_factory=UpstreamAuthConfig)
    transport_type: MCPTransportType = "stateless_http"
    requires_gateway: bool = False
    gateway_url: str | None = None
    auth_requirement: ProviderAuthRequirement | None = None


class ExecuteResponse(BaseModel):
    """Structured result from proxied tool execution."""

    status: ExecuteStatus = "ok"
    tool_id: str
    server_id: str
    auth: AuthRequiredPayload | None = None
    result: dict | None = None
    error: str | None = None
    latency_ms: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy_success_input(cls, data: object) -> object:
        if not isinstance(data, dict) or "status" in data or "success" not in data:
            return data

        data = dict(data)
        data["status"] = "ok" if data.get("success") else "execution_failed"
        return data

    @computed_field
    @property
    def success(self) -> bool:
        return self.status == "ok"


class RegisterToolEntry(BaseModel):
    """Single tool entry in a registration request."""

    tool_name: str
    description: str = ""
    input_schema: dict | None = None
    client_auth: RegisterClientAuthRequirement | None = None


class RegisterRequest(BaseModel):
    """Provider registration request payload."""

    server_id: str
    name: str
    description: str = ""
    url: str
    tags: list[str] = Field(default_factory=list)
    tools: list[RegisterToolEntry]
    execution_auth: UpstreamAuthConfig = Field(default_factory=UpstreamAuthConfig)
    client_auth: RegisterClientAuthRequirement | None = None
    transport_type: MCPTransportType = "stateless_http"
    requires_gateway: bool = False


class ParameterMetadataEntry(BaseModel):
    """Normalized JSON Schema parameter summary for review surfaces."""

    path: str
    name: str
    type: str | None = None
    required: bool = False
    description: str | None = None
    enum_values: list[str] = Field(default_factory=list)
    default_value: object | None = None
    items_type: str | None = None
    object_properties_count: int | None = None


class PublishedParameterMetadataEntry(BaseModel):
    """Published parameter-description override."""

    path: str
    description: str | None = None


class DiscoveredTool(BaseModel):
    """Normalized tool metadata discovered from an upstream MCP tools/list response."""

    tool_name: str
    upstream_description: str = ""
    input_schema: dict | None = None
    parameter_metadata: list[ParameterMetadataEntry] = Field(default_factory=list)


class MetadataDiscoveryResponse(BaseModel):
    """Structured response returned by HTTP MCP metadata discovery."""

    url: str
    tools: list[DiscoveredTool]
    warnings: list[str] = Field(default_factory=list)


class ToolParameterChangeEntry(BaseModel):
    """Single parameter-level metadata diff item for a tool refresh preview."""

    path: str
    change_type: Literal["added", "removed", "changed"]
    severity: Literal["info", "warning"] = "info"
    upstream_description: str | None = None
    published_description: str | None = None


class ToolMetadataDiffEntry(BaseModel):
    """Single metadata diff item for a tool between stored and upstream snapshots."""

    tool_name: str
    change_type: Literal["added", "removed", "changed"]
    upstream_description: str | None = None
    effective_description: str | None = None
    schema_changed: bool = False
    severity: Literal["info", "warning"] = "info"
    parameter_changes: list[ToolParameterChangeEntry] = Field(default_factory=list)
    orphaned_parameter_paths: list[str] = Field(default_factory=list)


class ToolMetadataDiffResult(BaseModel):
    """Grouped metadata diff result used by refresh-preview workflows."""

    server_id: str
    changed: list[ToolMetadataDiffEntry] = Field(default_factory=list)
    added: list[ToolMetadataDiffEntry] = Field(default_factory=list)
    removed: list[ToolMetadataDiffEntry] = Field(default_factory=list)
