export type MCPTransportType = 'stateless_http' | 'streamable_http' | 'sse' | 'stdio';
export type HostedConnectReuseScope = 'user' | 'client_app';
export type ClientConnectAuthType = 'oauth' | 'api_key';
export type ProviderConnectAuthType = 'none' | 'oauth' | 'api_key';

export type UpstreamAuthType =
  | 'none'
  | 'bearer'
  | 'api_key_header'
  | 'custom_headers'
  | 'oauth_session';
export type ClientAuthScopeMode = 'default' | 'override';

export interface UpstreamAuthConfig {
  auth_type: UpstreamAuthType;
  bearer_token?: string;
  api_key_header_name?: string;
  api_key?: string;
  headers?: Record<string, string>;
  oauth_token_endpoint?: string;
  oauth_client_id?: string;
  oauth_client_secret?: string;
  oauth_refresh_token?: string;
  oauth_scope?: string;
}

export interface ClientAuthConfig {
  provider_key: string;
  required_scopes: string[];
  scope_mode: ClientAuthScopeMode;
}


export type OAuthProviderTokenEndpointAuthMethod = 'none' | 'client_secret_post' | 'client_secret_basic';
export type OAuthProviderBootstrapMode = 'manual' | 'discovery' | 'dcr';
export type OAuthProviderBootstrapStatus = 'draft' | 'validated' | 'enabled' | 'failed' | 'disabled' | 'promoted';

export interface OAuthProviderBootstrapResponse {
  draft_id?: string | null;
  provider_key: string;
  status: OAuthProviderBootstrapStatus;
  mode: OAuthProviderBootstrapMode;
  metadata: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
  idempotency_key?: string | null;
}

export interface OAuthProviderBootstrapManualRequest {
  provider_key: string;
  display_name: string;
  authorize_url: string;
  token_url: string;
  client_id: string;
  client_secret?: string;
  token_endpoint_auth_method: OAuthProviderTokenEndpointAuthMethod;
  default_scopes?: string[];
  issuer?: string;
  supports_refresh_token?: boolean;
  pkce_required?: boolean;
}

export interface OAuthProviderBootstrapDiscoverRequest {
  provider_key: string;
  display_name?: string;
  issuer?: string;
  authorization_server_metadata_url?: string;
  openid_configuration_url?: string;
  protected_resource_metadata_url?: string;
  selected_authorization_server?: string;
  client_id?: string;
  client_secret?: string;
  token_endpoint_auth_method?: OAuthProviderTokenEndpointAuthMethod;
  default_scopes?: string[];
  supports_refresh_token?: boolean;
  pkce_required?: boolean;
}

export interface OAuthProviderBootstrapDcrRequest {
  provider_key: string;
  display_name: string;
  registration_endpoint: string;
  authorize_url: string;
  token_url: string;
  client_name: string;
  token_endpoint_auth_method: OAuthProviderTokenEndpointAuthMethod;
  scopes?: string[];
  default_scopes?: string[];
  supports_refresh_token?: boolean;
  issuer?: string;
}

export interface MCPServer {
  id: string;
  server_id: string;
  name: string;
  description: string | null;
  url: string | null;
  tags: string[] | null;
  index_status: 'pending' | 'indexed' | 'failed';
  created_at: string;
  updated_at: string;
}

export interface GEOScore {
  clarity: number;
  disambiguation: number;
  parameter_coverage: number;
  boundary: number;
  stats: number;
  precision: number;
  total: number;
}

export interface MCPTool {
  id?: string;
  tool_id: string;
  server_id: string;
  tool_name: string;
  description?: string | null;
  upstream_description?: string | null;
  parameter_notes?: string | null;
  usage_examples?: string[] | null;
  usage_hints?: string[] | null;
  metadata_origin?: 'manual' | 'discovered' | 'mixed' | null;
  metadata_last_fetched_at?: string | null;
  override_updated_at?: string | null;
  input_schema?: Record<string, unknown> | null;
  geo_score: GEOScore | null;
  index_status: string;
  created_at?: string;
}

export interface SearchResult {
  tool: {
    tool_id: string;
    server_id: string;
    tool_name: string;
    description: string;
  };
  score: number;
  rank: number;
  reason: string | null;
  input_schema: Record<string, unknown> | null;
  score_breakdown: {
    relevance: number;
    quality: number;
    boost: number;
  } | null;
  is_boosted: boolean;
}

export interface SearchResponse {
  results: SearchResult[];
  query: string;
  strategy?: string;
  strategy_used?: string;
  latency_ms: number;
  confidence?: number;
  degraded?: boolean;
  disambiguation_needed?: boolean;
  source_path?: string[];
}

export interface PlatformStatsResponse {
  server_count: number;
  tool_count: number;
  indexed_count: number;
  avg_geo_score: number | null;
}

export interface ServerListItem extends MCPServer {
  tool_count: number;
}

export interface ServerListResponse {
  items: ServerListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface ServerDetailResponse {
  server: MCPServer;
  tools: MCPTool[];
}

export interface ToolDetailResponse {
  tool: MCPTool;
  server: Pick<MCPServer, 'name' | 'server_id' | 'url'> | null;
}

export interface ProviderDashboardSummary {
  total_tools: number;
  avg_geo_score: number;
  needs_improvement: number;
  indexed_count: number;
}

export interface ProviderDashboardTool extends MCPTool {
  server_name?: string;
  auth_posture?: 'public' | 'provider_managed' | 'client_oauth_required' | 'client_api_key_required';
  client_auth_mode?: 'none' | ClientConnectAuthType;
  connect_supported?: boolean;
  connection_reuse_scope?: HostedConnectReuseScope;
  // Optional analytics fields surfaced in dashboard sections
  times_exposed?: number | null;
  times_selected?: number | null;
  selection_rate?: number | null;
  selection_rate_7d?: number | null;
  call_count?: number | null;
  success_rate?: number | null;
  avg_latency_ms?: number | null;
  p95_latency_ms?: number | null;
  avg_score_when_exposed?: number | null;
  last_indexed_at?: string | null;
  reachability_status?: 'healthy' | 'degraded' | 'unreachable' | string | null;
  reachability_latency_ms?: number | null;
}

export interface ProviderDashboardResponse {
  summary: ProviderDashboardSummary;
  tools: ProviderDashboardTool[];
}

export interface ProviderToolSimulation {
  recommended_tool_id: string;
  server_id: string;
  query_count: number | string;
  avg_confidence: number | string | null;
  avg_latency_ms: number | string | null;
  high_confidence_count: number | string;
}

export interface HostedConnectScope {
  reuse_scope: HostedConnectReuseScope;
  client_app_id?: string | null;
}

export interface HostedConnectSessionResponse {
  connect_session_id: string;
  actor_type: 'provider' | 'client';
  end_user_id: string;
  client_app_id?: string | null;
  server_id: string;
  tool_name?: string | null;
  auth_type: ClientConnectAuthType;
  status: 'created' | 'awaiting_user_approval' | 'completed';
  scope: HostedConnectScope;
  start_url?: string;
}

export interface ClientConnectSessionRequest {
  provider_key?: string;
  server_id: string;
  tool_name?: string;
  tool_id?: string;
  client_app_id?: string;
  auth_type: ClientConnectAuthType;
  pending_execution_id?: string;
}

export interface PendingExecutionResponse {
  pending_execution_id: string;
  resume_token: string;
  status: 'waiting_for_connect' | 'ready_to_resume' | 'resuming' | 'resumed' | 'failed';
  end_user_id: string;
  client_app_id?: string | null;
  server_id: string;
  tool_name: string;
  original_params: Record<string, unknown>;
  required_auth_type: ClientConnectAuthType;
  connection_scope: HostedConnectScope;
  connect_session_id?: string | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
}

export interface PendingExecutionResumeRequest {
  client_app_id?: string;
}

export interface ProviderConnectDiscoveryRequest {
  server_id: string;
  url: string;
}

export interface ProviderConnectSessionResponse {
  connect_session_id: string;
  provider_user_id: string;
  server_id: string;
  url: string;
  auth_type: ProviderConnectAuthType;
  start_url?: string;
  callback_received_at?: string;
  status: 'created' | 'awaiting_provider_approval' | 'connected';
}

export interface ProviderConnectCompleteRequest {
  connect_session_id: string;
  state: string;
  access_token?: string;
  code?: string;
}

export interface ProviderConnectionResponse {
  provider_user_id: string;
  server_id: string;
  connect_session_id: string;
  auth_type: ProviderConnectAuthType;
  status: 'connected';
}

export interface ProviderToolDetailResponse {
  tool: ProviderDashboardTool & { server_url?: string | null };
  competitors: ProviderDashboardTool[];
  simulations: ProviderToolSimulation[];
}

export interface UpdateProviderToolMetadataRequest {
  description?: string;
  parameter_notes?: string;
  usage_examples?: string[];
  usage_hints?: string[];
}

export interface ProviderToolMetadataRefreshRequest {
  url?: string;
  execution_auth?: UpstreamAuthConfig;
}

export interface ToolMetadataDiffEntry {
  tool_name: string;
  change_type: 'added' | 'removed' | 'changed';
  upstream_description?: string | null;
  effective_description?: string | null;
  schema_changed: boolean;
  severity: 'info' | 'warning';
}

export interface ToolMetadataDiffResult {
  server_id: string;
  changed: ToolMetadataDiffEntry[];
  added: ToolMetadataDiffEntry[];
  removed: ToolMetadataDiffEntry[];
  warnings?: string[];
}

export interface ApplyProviderToolMetadataRefreshResponse {
  tool: ProviderDashboardTool & { server_url?: string | null };
  preview: ToolMetadataDiffResult;
}

export interface ParameterMetadataEntry {
  path: string;
  name: string;
  type?: string | null;
  required: boolean;
  description?: string | null;
  enum_values: string[];
  default_value?: unknown | null;
  items_type?: string | null;
  object_properties_count?: number | null;
}

export interface PublishedParameterMetadataEntry {
  path: string;
  description?: string | null;
}

export interface DiscoveredToolResponse {
  tool_name: string;
  upstream_description: string;
  input_schema: Record<string, unknown> | null;
  parameter_metadata: ParameterMetadataEntry[];
}

export interface RegisterDiscoveryRequest {
  server_id?: string;
  url: string;
  execution_auth?: UpstreamAuthConfig;
}

export interface RegisterDiscoveryResponse {
  url: string;
  tools: DiscoveredToolResponse[];
  warnings: string[];
}

export interface RegisterToolRequest {
  tool_name: string;
  description?: string;
  upstream_description?: string;
  input_schema?: Record<string, unknown> | null;
  client_auth?: ClientAuthConfig;
  parameter_metadata?: ParameterMetadataEntry[];
  published_parameter_metadata?: PublishedParameterMetadataEntry[];
  parameter_notes?: string;
  usage_examples?: string[];
  usage_hints?: string[];
}

export interface RegisterServerRequest {
  server_id: string;
  name: string;
  description?: string;
  url: string;
  tags?: string[];
  execution_auth?: UpstreamAuthConfig;
  client_auth?: ClientAuthConfig;
  transport_type?: MCPTransportType;
  requires_gateway?: boolean;
  tools: RegisterToolRequest[];
}

export interface RegisterServerResponse {
  server_id: string;
  tools_count: number;
  message: string;
}
