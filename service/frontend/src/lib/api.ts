import { toast } from 'sonner';
import { config } from './config';
import type {
  ApplyProviderToolMetadataRefreshResponse,
  ClientConnectSessionRequest,
  HostedConnectSessionResponse,
  OAuthProviderBootstrapDcrRequest,
  OAuthProviderBootstrapDiscoverRequest,
  OAuthProviderBootstrapManualRequest,
  OAuthProviderBootstrapResponse,
  PendingExecutionResponse,
  PendingExecutionResumeRequest,
  PlatformStatsResponse,
  ProviderConnectionResponse,
  ProviderConnectCompleteRequest,
  ProviderConnectDiscoveryRequest,
  ProviderConnectSessionResponse,
  ProviderDashboardResponse,
  ProviderToolDetailResponse,
  ProviderToolMetadataRefreshRequest,
  RegisterDiscoveryRequest,
  RegisterDiscoveryResponse,
  RegisterServerRequest,
  RegisterServerResponse,
  SearchResponse,
  ServerDetailResponse,
  ServerListResponse,
  ToolDetailResponse,
  ToolMetadataDiffResult,
  UpdateProviderToolMetadataRequest,
} from '@/types/database';

async function fetchJson<T>(path: string, init: RequestInit = {}, accessToken?: string): Promise<T> {
  const headers = new Headers(init.headers || {});
  headers.set('x-api-key', config.api.key);
  if (!headers.has('Content-Type') && init.method && init.method !== 'GET') {
    headers.set('Content-Type', 'application/json');
  }
  if (accessToken) {
    headers.set('authorization', `Bearer ${accessToken}`);
  }

  const res = await fetch(`${config.api.url}${path}`, {
    ...init,
    headers,
  });

  if (res.status === 429) {
    toast.error('Rate limit reached. Please try again in a moment.');
    throw new Error('Rate limit reached');
  }

  if (res.status === 401) {
    throw new Error('Unauthorized');
  }

  if (res.status >= 500) {
    let detail: string | null = null;
    try {
      const body = await res.clone().json() as { error?: string };
      if (body?.error) detail = body.error;
    } catch {
      // body was not JSON or already consumed — fall back to generic message below
    }
    toast.error(detail ?? 'Service temporarily unavailable');
    throw new Error(detail ?? `Server error: ${res.status}`);
  }

  if (!res.ok) {
    try {
      const body = await res.json() as { error?: string };
      if (body?.error) {
        throw new Error(body.error);
      }
    } catch (error) {
      if (error instanceof Error && error.message) {
        throw error;
      }
    }

    throw new Error(`Request failed: ${res.status} ${res.statusText}`);
  }

  return res.json() as Promise<T>;
}

export async function searchTools(query: string, topK: number = 5): Promise<SearchResponse> {
  return fetchJson<SearchResponse>('/api/search', {
    method: 'POST',
    body: JSON.stringify({ query, top_k: topK }),
  });
}

export async function getPlatformStats(): Promise<PlatformStatsResponse> {
  return fetchJson<PlatformStatsResponse>('/api/platform/stats', { method: 'GET' });
}

export async function listServers(limit: number = 50, offset: number = 0): Promise<ServerListResponse> {
  return fetchJson<ServerListResponse>(`/api/servers?limit=${limit}&offset=${offset}`, { method: 'GET' });
}

export async function getServerDetail(serverId: string): Promise<ServerDetailResponse> {
  return fetchJson<ServerDetailResponse>(`/api/servers/${encodeURIComponent(serverId)}`, { method: 'GET' });
}

export async function getToolDetail(toolId: string): Promise<ToolDetailResponse> {
  return fetchJson<ToolDetailResponse>(`/api/tools/${encodeURIComponent(toolId)}`, { method: 'GET' });
}

export async function getProviderDashboard(accessToken: string): Promise<ProviderDashboardResponse> {
  return fetchJson<ProviderDashboardResponse>('/api/providers/dashboard', { method: 'GET' }, accessToken);
}

export async function getProviderToolDetail(
  accessToken: string,
  toolId: string,
): Promise<ProviderToolDetailResponse> {
  return fetchJson<ProviderToolDetailResponse>(
    `/api/providers/tools/${encodeURIComponent(toolId)}`,
    { method: 'GET' },
    accessToken,
  );
}

export async function updateProviderToolMetadata(
  accessToken: string,
  toolId: string,
  payload: UpdateProviderToolMetadataRequest,
): Promise<Partial<ProviderToolDetailResponse['tool']>> {
  return fetchJson<Partial<ProviderToolDetailResponse['tool']>>(
    `/api/providers/tools/${encodeURIComponent(toolId)}`,
    {
      method: 'PUT',
      body: JSON.stringify(payload),
    },
    accessToken,
  );
}

export async function previewProviderToolMetadataRefresh(
  accessToken: string,
  toolId: string,
  payload?: ProviderToolMetadataRefreshRequest,
): Promise<ToolMetadataDiffResult> {
  return fetchJson<ToolMetadataDiffResult>(
    `/api/providers/tools/${encodeURIComponent(toolId)}/metadata-refresh-preview`,
    {
      method: 'POST',
      body: JSON.stringify(payload ?? {}),
    },
    accessToken,
  );
}

export async function applyProviderToolMetadataRefresh(
  accessToken: string,
  toolId: string,
  payload?: ProviderToolMetadataRefreshRequest,
): Promise<ApplyProviderToolMetadataRefreshResponse> {
  return fetchJson<ApplyProviderToolMetadataRefreshResponse>(
    `/api/providers/tools/${encodeURIComponent(toolId)}/metadata-refresh-apply`,
    {
      method: 'POST',
      body: JSON.stringify(payload ?? {}),
    },
    accessToken,
  );
}

export async function discoverProviderServerMetadata(
  accessToken: string,
  payload: RegisterDiscoveryRequest,
): Promise<RegisterDiscoveryResponse> {
  const body = JSON.stringify(payload);

  return fetchJson<RegisterDiscoveryResponse>(
    '/api/providers/servers/discovery',
    {
      method: 'POST',
      body,
    },
    accessToken,
  );
}

/**
 * Hosted-connect discovery handshake.
 *
 * The `/api/providers/connect/discover` route is implemented in
 * `service/api/local_app.py` (FastAPI local stub) but is NOT yet deployed
 * as an AWS Lambda + API Gateway route. This client function should only
 * fire when `config.hostedConnect.enabled === true` (currently `false` in
 * the production Vercel build, gated by `VITE_HOSTED_CONNECT_ENABLED`).
 *
 * If the flag is ever flipped to `true` without the backend Lambda
 * shipping first, this call will return HTTP 404 and the registration
 * wizard will surface a generic error. See `service/docs/runbook.md`
 * section 11.1 for the deployment ordering.
 */
export async function discoverProviderConnect(
  accessToken: string,
  payload: ProviderConnectDiscoveryRequest,
): Promise<ProviderConnectSessionResponse> {
  return fetchJson<ProviderConnectSessionResponse>(
    '/api/providers/connect/discover',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    accessToken,
  );
}

export async function validateProviderConnectCallback(
  accessToken: string,
  params: URLSearchParams,
): Promise<ProviderConnectSessionResponse> {
  const query = params.toString();
  return fetchJson<ProviderConnectSessionResponse>(
    `/api/providers/connect/callback${query ? `?${query}` : ''}`,
    { method: 'GET' },
    accessToken,
  );
}

export async function completeProviderConnect(
  accessToken: string,
  payload: ProviderConnectCompleteRequest,
): Promise<ProviderConnectionResponse> {
  return fetchJson<ProviderConnectionResponse>(
    '/api/providers/connect/callback',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    accessToken,
  );
}

export async function createClientConnectSession(
  accessToken: string,
  payload: ClientConnectSessionRequest,
): Promise<HostedConnectSessionResponse> {
  return fetchJson<HostedConnectSessionResponse>(
    '/api/client-connections/session',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    accessToken,
  );
}

export async function resumePendingExecution(
  accessToken: string,
  resumeToken: string,
  payload: PendingExecutionResumeRequest = {},
): Promise<PendingExecutionResponse> {
  return fetchJson<PendingExecutionResponse>(
    `/api/pending-executions/${encodeURIComponent(resumeToken)}/resume`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    accessToken,
  );
}

export async function registerProviderServer(
  accessToken: string,
  payload: RegisterServerRequest,
): Promise<RegisterServerResponse> {
  const body = JSON.stringify(payload);

  return fetchJson<RegisterServerResponse>(
    '/api/servers',
    {
      method: 'POST',
      body,
    },
    accessToken,
  );
}

export async function getProviderProfile(accessToken: string): Promise<Record<string, unknown>> {
  return fetchJson<Record<string, unknown>>('/api/providers/profile', { method: 'GET' }, accessToken);
}

export async function updateProviderProfile(
  accessToken: string,
  data: Record<string, string>,
): Promise<Record<string, unknown>> {
  return fetchJson<Record<string, unknown>>(
    '/api/providers/profile',
    {
      method: 'PUT',
      body: JSON.stringify(data),
    },
    accessToken,
  );
}

export async function getToolAnalytics(toolId: string, accessToken: string): Promise<Record<string, unknown>> {
  return fetchJson<Record<string, unknown>>(
    `/api/providers/tools/${encodeURIComponent(toolId)}/analytics`,
    { method: 'GET' },
    accessToken,
  );
}

export async function getToolInsights(toolId: string, accessToken: string): Promise<Record<string, unknown>> {
  return fetchJson<Record<string, unknown>>(
    `/api/providers/tools/${encodeURIComponent(toolId)}/insights`,
    { method: 'GET' },
    accessToken,
  );
}


export async function discoverOAuthProviderBootstrap(
  accessToken: string,
  payload: OAuthProviderBootstrapDiscoverRequest,
): Promise<OAuthProviderBootstrapResponse> {
  return fetchJson<OAuthProviderBootstrapResponse>(
    '/api/oauth/providers/bootstrap/discover',
    { method: 'POST', body: JSON.stringify(payload) },
    accessToken,
  );
}

export async function runOAuthProviderDcrBootstrap(
  accessToken: string,
  payload: OAuthProviderBootstrapDcrRequest,
): Promise<OAuthProviderBootstrapResponse> {
  return fetchJson<OAuthProviderBootstrapResponse>(
    '/api/oauth/providers/bootstrap/dcr',
    { method: 'POST', body: JSON.stringify(payload) },
    accessToken,
  );
}

export async function createOAuthProviderManualBootstrap(
  accessToken: string,
  payload: OAuthProviderBootstrapManualRequest,
): Promise<OAuthProviderBootstrapResponse> {
  return fetchJson<OAuthProviderBootstrapResponse>(
    '/api/oauth/providers/bootstrap/manual',
    { method: 'POST', body: JSON.stringify(payload) },
    accessToken,
  );
}

export async function enableOAuthProviderBootstrap(
  accessToken: string,
  providerKey: string,
  draftId: string,
): Promise<Record<string, unknown>> {
  return fetchJson<Record<string, unknown>>(
    `/api/oauth/providers/${encodeURIComponent(providerKey)}/enable`,
    { method: 'POST', body: JSON.stringify({ draft_id: draftId }) },
    accessToken,
  );
}
