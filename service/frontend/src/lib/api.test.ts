import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  createOAuthProviderManualBootstrap,
  enableOAuthProviderBootstrap,
  createClientConnectSession,
  discoverProviderServerMetadata,
  getPlatformStats,
  getProviderDashboard,
  registerProviderServer,
  resumePendingExecution,
} from "./api";

describe("api client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("calls platform stats endpoint with API key", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ server_count: 1, tool_count: 2, indexed_count: 2, avg_geo_score: 0.1 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await getPlatformStats();

    expect(result.server_count).toBe(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/platform/stats");
    expect(init.method).toBe("GET");
    expect(init.headers.get("x-api-key")).toBeDefined();
  });

  it("sends bearer token for provider dashboard endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ summary: { total_tools: 1 }, tools: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await getProviderDashboard("access-token-123");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/providers/dashboard");
    expect(init.method).toBe("GET");
    expect(init.headers.get("authorization")).toBe("Bearer access-token-123");
    expect(init.headers.get("x-api-key")).toBeDefined();
  });

  it("posts provider discovery payloads with auth metadata", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        url: "https://provider.test/mcp",
        tools: [
          {
            tool_name: "lookup",
            upstream_description: "Lookup docs",
            input_schema: { type: "object" },
            parameter_metadata: [
              {
                path: "q",
                name: "q",
                type: "string",
                required: true,
                description: "Search query",
                enum_values: [],
                default_value: null,
                items_type: null,
                object_properties_count: null,
              },
            ],
          },
        ],
        warnings: [],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = {
      server_id: "srv-provider",
      url: "https://provider.test/mcp",
      execution_auth: {
        auth_type: "bearer" as const,
        bearer_token: "secret-token",
      },
    };

    const result = await discoverProviderServerMetadata("access-token-123", payload);

    expect(result.tools[0].tool_name).toBe("lookup");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/providers/servers/discovery");
    expect(init.method).toBe("POST");
    expect(init.headers.get("authorization")).toBe("Bearer access-token-123");
    expect(init.headers.get("x-api-key")).toBeDefined();
    expect(init.headers.get("Content-Type")).toBe("application/json");
    expect(init.body).toBe(JSON.stringify(payload));
  });

  it("posts the authenticated provider registration payload with override metadata", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        server_id: "srv-weather",
        tools_count: 1,
        message: "Server registered. Indexing in progress.",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = {
      server_id: "srv-weather",
      name: "Weather Server",
      description: "Weather lookup tools",
      url: "https://weather.test/mcp",
      tags: ["weather", "forecast"],
      execution_auth: {
        auth_type: "none" as const,
      },
      client_auth: {
        provider_key: "github",
        required_scopes: ["repo", "issues:write"],
        scope_mode: "override" as const,
      },
      transport_type: "stateless_http" as const,
      requires_gateway: false,
      tools: [
        {
          tool_name: "forecast",
          description: "Get the published weather forecast",
          upstream_description: "Get forecast data from upstream",
          input_schema: {
            type: "object",
            properties: {
              city: { type: "string" },
            },
          },
          parameter_metadata: [
            {
              path: "city",
              name: "city",
              type: "string",
              required: true,
              description: "City name",
              enum_values: [],
              default_value: null,
              items_type: null,
              object_properties_count: null,
            },
          ],
          published_parameter_metadata: [
            {
              path: "city",
              description: "City to use for the weather lookup",
            },
          ],
          parameter_notes: "Use city for exact weather lookups",
          usage_examples: ['{"city": "Seoul"}'],
          usage_hints: ["Best for current and daily forecast requests"],
        },
      ],
    };

    const result = await registerProviderServer("access-token-123", payload);

    expect(result.server_id).toBe("srv-weather");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/servers");
    expect(init.method).toBe("POST");
    expect(init.headers.get("authorization")).toBe("Bearer access-token-123");
    expect(init.headers.get("x-api-key")).toBeDefined();
    expect(init.headers.get("Content-Type")).toBe("application/json");
    expect(init.body).toBe(JSON.stringify(payload));
  });

  it("creates client connect sessions with bearer auth", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        connect_session_id: 'connect-123',
        actor_type: 'client',
        end_user_id: 'user-123',
        server_id: 'srv',
        tool_name: 'lookup',
        auth_type: 'oauth',
        status: 'awaiting_user_approval',
        scope: { reuse_scope: 'user', client_app_id: null },
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const payload = {
      server_id: 'srv',
      tool_name: 'lookup',
      auth_type: 'oauth' as const,
    };

    const result = await createClientConnectSession('access-token-123', payload);

    expect(result.connect_session_id).toBe('connect-123');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/client-connections/session');
    expect(init.method).toBe('POST');
    expect(init.headers.get('authorization')).toBe('Bearer access-token-123');
    expect(init.body).toBe(JSON.stringify(payload));
  });

  it("posts resume tokens for pending execution handoff", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        pending_execution_id: 'pending-123',
        resume_token: 'resume-123',
        status: 'resumed',
        end_user_id: 'user-123',
        server_id: 'srv',
        tool_name: 'lookup',
        original_params: { query: 'docs' },
        required_auth_type: 'oauth',
        connection_scope: { reuse_scope: 'user', client_app_id: null },
      }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await resumePendingExecution('access-token-123', 'resume-123', { client_app_id: 'dashboard-web' });

    expect(result.status).toBe('resumed');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/pending-executions/resume-123/resume');
    expect(init.method).toBe('POST');
    expect(init.headers.get('authorization')).toBe('Bearer access-token-123');
    expect(init.body).toBe(JSON.stringify({ client_app_id: 'dashboard-web' }));
  });


  it("bootstraps and enables OAuth providers", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          draft_id: 'draft-1',
          provider_key: 'github',
          status: 'validated',
          mode: 'manual',
          metadata: {},
          diagnostics: {},
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ provider_key: 'github', enabled: true }),
      });
    vi.stubGlobal('fetch', fetchMock);

    const payload = {
      provider_key: 'github',
      display_name: 'GitHub',
      authorize_url: 'https://github.com/login/oauth/authorize',
      token_url: 'https://github.com/login/oauth/access_token',
      client_id: 'client-id',
      client_secret: 'client-secret',
      token_endpoint_auth_method: 'client_secret_post' as const,
    };

    const draft = await createOAuthProviderManualBootstrap('access-token-123', payload);
    await enableOAuthProviderBootstrap('access-token-123', 'github', draft.draft_id ?? '');

    expect(draft.draft_id).toBe('draft-1');
    expect(fetchMock.mock.calls[0][0]).toContain('/api/oauth/providers/bootstrap/manual');
    expect(fetchMock.mock.calls[0][1].headers.get('authorization')).toBe('Bearer access-token-123');
    expect(fetchMock.mock.calls[0][1].body).toBe(JSON.stringify(payload));
    expect(fetchMock.mock.calls[1][0]).toContain('/api/oauth/providers/github/enable');
    expect(fetchMock.mock.calls[1][1].body).toBe(JSON.stringify({ draft_id: 'draft-1' }));
  });

  it("surfaces backend error messages for registration failures", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      statusText: "Bad Request",
      json: async () => ({ error: "Missing required fields: server_id, name, url" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      registerProviderServer("access-token-123", {
        server_id: "",
        name: "",
        url: "",
        tools: [{ tool_name: "lookup", description: "" }],
      }),
    ).rejects.toThrow("Missing required fields: server_id, name, url");
  });
});
