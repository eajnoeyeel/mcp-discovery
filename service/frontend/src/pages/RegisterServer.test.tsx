import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigate = vi.fn();
const discoverProviderConnect = vi.fn();
const discoverProviderServerMetadata = vi.fn();
const registerProviderServer = vi.fn();

const configFlags = vi.hoisted(() => ({ hostedConnectEnabled: true }));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

vi.mock("@/lib/config", () => ({
  config: {
    api: { isConfigured: true, url: "http://api.test", key: "test-key" },
    supabase: { isConfigured: true, url: "http://supabase.test", anonKey: "anon" },
    hostedConnect: {
      get enabled() {
        return configFlags.hostedConnectEnabled;
      },
    },
  },
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    session: { access_token: "access-token-123" },
    user: { id: "user-123" },
    loading: false,
  }),
}));

vi.mock("@/lib/api", () => ({
  discoverProviderConnect: (...args: unknown[]) => discoverProviderConnect(...args),
  discoverProviderServerMetadata: (...args: unknown[]) => discoverProviderServerMetadata(...args),
  registerProviderServer: (...args: unknown[]) => registerProviderServer(...args),
}));

import RegisterServer from "./RegisterServer";

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <RegisterServer />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RegisterServer page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    configFlags.hostedConnectEnabled = true;
    discoverProviderConnect.mockResolvedValue({
      connect_session_id: 'connect-123',
      provider_user_id: 'user-123',
      server_id: 'srv',
      url: 'https://provider.test/mcp',
      auth_type: 'none',
      status: 'created',
    });
    discoverProviderServerMetadata.mockResolvedValue({
      url: "https://provider.test/mcp",
      tools: [
        {
          tool_name: "lookup",
          upstream_description: "Lookup docs",
          input_schema: {
            type: "object",
            properties: { q: { type: "string" } },
          },
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
    });
    registerProviderServer.mockResolvedValue({
      server_id: "srv",
      tools_count: 1,
      message: "Server registered. Indexing in progress.",
    });
  });

  it("allows manual continuation when discovery fails", async () => {
    discoverProviderServerMetadata.mockRejectedValue(new Error("401 Unauthorized"));
    renderPage();

    fireEvent.change(screen.getByLabelText(/server id/i), { target: { value: "srv" } });
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: "Owned Server" } });
    fireEvent.change(screen.getByLabelText(/^server url$/i), { target: { value: "https://provider.test/mcp" } });

    fireEvent.click(screen.getByRole("button", { name: /fetch metadata/i }));

    await waitFor(() => {
      expect(screen.getByText(/automatic metadata fetch failed/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /continue manually/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /review tool metadata/i })).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/tool name/i)).toBeInTheDocument();
    expect(registerProviderServer).not.toHaveBeenCalled();
  });

  it("rejects duplicate manual tool names before continuing", async () => {
    discoverProviderServerMetadata.mockRejectedValue(new Error("401 Unauthorized"));
    renderPage();

    fireEvent.change(screen.getByLabelText(/server id/i), { target: { value: "srv" } });
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: "Owned Server" } });
    fireEvent.change(screen.getByLabelText(/^server url$/i), { target: { value: "https://provider.test/mcp" } });

    fireEvent.click(screen.getByRole("button", { name: /fetch metadata/i }));

    await waitFor(() => {
      expect(screen.getByText(/automatic metadata fetch failed/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /continue manually/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /review tool metadata/i })).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/tool name/i), { target: { value: "lookup" } });
    fireEvent.click(screen.getByRole("button", { name: /add another tool/i }));
    fireEvent.change(screen.getByLabelText(/tool name/i, { selector: "#tool-name-1" }), {
      target: { value: "  LOOKUP  " },
    });

    fireEvent.click(screen.getByRole("button", { name: /continue to published metadata/i }));

    await waitFor(() => {
      expect(screen.getByText(/duplicate tool names are not allowed/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: /review tool metadata/i })).toBeInTheDocument();
    expect(registerProviderServer).not.toHaveBeenCalled();
  });

  it("shows structured parameter metadata from discovery during the review step", async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText(/server id/i), { target: { value: "srv" } });
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: "Owned Server" } });
    fireEvent.change(screen.getByLabelText(/^server url$/i), { target: { value: "https://provider.test/mcp" } });

    fireEvent.click(screen.getByRole("button", { name: /fetch metadata/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /review tool metadata/i })).toBeInTheDocument();
    });

    expect(screen.getByText(/structured parameter summary/i)).toBeInTheDocument();
    expect(screen.getByText("q")).toBeInTheDocument();
    expect(screen.getByText(/^Required$/i)).toBeInTheDocument();
    expect(screen.getByText("string")).toBeInTheDocument();
    expect(screen.getByText("Search query")).toBeInTheDocument();
  });

  it("shows the raw schema fallback when structured parameter metadata is unavailable", async () => {
    discoverProviderServerMetadata.mockResolvedValueOnce({
      url: "https://provider.test/mcp",
      tools: [
        {
          tool_name: "lookup",
          upstream_description: "Lookup docs",
          input_schema: {
            type: "object",
            properties: { q: { type: "string" } },
          },
          parameter_metadata: [],
        },
      ],
      warnings: [],
    });

    renderPage();

    fireEvent.change(screen.getByLabelText(/server id/i), { target: { value: "srv" } });
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: "Owned Server" } });
    fireEvent.change(screen.getByLabelText(/^server url$/i), { target: { value: "https://provider.test/mcp" } });

    fireEvent.click(screen.getByRole("button", { name: /fetch metadata/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /review tool metadata/i })).toBeInTheDocument();
    });

    expect(screen.getByText(/structured parameter metadata unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/review the raw input schema below/i)).toBeInTheDocument();
    expect(screen.getByText(/input schema fallback/i)).toBeInTheDocument();
  });

  it("does not serialize published_parameter_metadata for untouched discovered parameters", async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText(/server id/i), { target: { value: "srv" } });
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: "Owned Server" } });
    fireEvent.change(screen.getByLabelText(/^server url$/i), { target: { value: "https://provider.test/mcp" } });

    fireEvent.click(screen.getByRole("button", { name: /fetch metadata/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /review tool metadata/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /continue to published metadata/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /edit published metadata/i })).toBeInTheDocument();
    });

    expect(screen.getByLabelText(/published description for q/i)).toHaveValue("");

    fireEvent.change(screen.getByLabelText(/^published description$/i), {
      target: { value: "Find the best matching document for a query." },
    });

    fireEvent.click(screen.getByRole("button", { name: /continue to confirmation/i }));
    fireEvent.click(screen.getByRole("button", { name: /register server/i }));

    await waitFor(() => {
      expect(registerProviderServer).toHaveBeenCalledWith(
        "access-token-123",
        expect.objectContaining({
          tools: [
            expect.objectContaining({
              tool_name: "lookup",
              published_parameter_metadata: [],
            }),
          ],
        }),
      );
    });
  });

  it("removes a parameter override when the edited description is cleared", async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText(/server id/i), { target: { value: "srv" } });
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: "Owned Server" } });
    fireEvent.change(screen.getByLabelText(/^server url$/i), { target: { value: "https://provider.test/mcp" } });

    fireEvent.click(screen.getByRole("button", { name: /fetch metadata/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /review tool metadata/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /continue to published metadata/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /edit published metadata/i })).toBeInTheDocument();
    });

    const parameterDescriptionField = screen.getByLabelText(/published description for q/i);
    fireEvent.change(parameterDescriptionField, {
      target: { value: "Exact search string to send upstream." },
    });
    fireEvent.change(parameterDescriptionField, {
      target: { value: "" },
    });

    fireEvent.change(screen.getByLabelText(/^published description$/i), {
      target: { value: "Find the best matching document for a query." },
    });

    fireEvent.click(screen.getByRole("button", { name: /continue to confirmation/i }));
    fireEvent.click(screen.getByRole("button", { name: /register server/i }));

    await waitFor(() => {
      expect(registerProviderServer).toHaveBeenCalledWith(
        "access-token-123",
        expect.objectContaining({
          tools: [
            expect.objectContaining({
              tool_name: "lookup",
              published_parameter_metadata: [],
            }),
          ],
        }),
      );
    });
  });

  it("submits override metadata gathered through the wizard", async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText(/server id/i), { target: { value: "srv" } });
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: "Owned Server" } });
    fireEvent.change(screen.getByLabelText(/^server url$/i), { target: { value: "https://provider.test/mcp" } });

    fireEvent.click(screen.getByRole("button", { name: /fetch metadata/i }));

    await waitFor(() => {
      expect(discoverProviderServerMetadata).toHaveBeenCalledWith("access-token-123", {
        server_id: "srv",
        url: "https://provider.test/mcp",
        execution_auth: { auth_type: "none" },
      });
    });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /review tool metadata/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /continue to published metadata/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /edit published metadata/i })).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/^published description$/i), {
      target: { value: "Find the best matching document for a query." },
    });
    fireEvent.change(screen.getByLabelText(/parameter notes/i), {
      target: { value: "Use q for exact lookup requests." },
    });
    fireEvent.change(screen.getByLabelText(/usage examples/i), {
      target: { value: '{"q": "docs"}\n{"q": "api"}' },
    });
    fireEvent.change(screen.getByLabelText(/usage hints/i), {
      target: { value: "Best for exact identifiers\nGreat for provider docs" },
    });
    fireEvent.change(screen.getByLabelText(/published description for q/i), {
      target: { value: "Exact search string to send upstream." },
    });

    fireEvent.click(screen.getByRole("button", { name: /continue to confirmation/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /confirm registration/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /register server/i }));

    await waitFor(() => {
      expect(registerProviderServer).toHaveBeenCalledWith("access-token-123", {
        server_id: "srv",
        name: "Owned Server",
        description: undefined,
        url: "https://provider.test/mcp",
        tags: [],
        execution_auth: { auth_type: "none" },
        transport_type: "stateless_http",
        requires_gateway: false,
        tools: [
          {
            tool_name: "lookup",
            description: "Find the best matching document for a query.",
            upstream_description: "Lookup docs",
            input_schema: {
              type: "object",
              properties: { q: { type: "string" } },
            },
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
            published_parameter_metadata: [
              {
                path: "q",
                description: "Exact search string to send upstream.",
              },
            ],
            parameter_notes: "Use q for exact lookup requests.",
            usage_examples: ['{"q": "docs"}', '{"q": "api"}'],
            usage_hints: ["Best for exact identifiers", "Great for provider docs"],
          },
        ],
      });
    });
    expect(navigate).toHaveBeenCalledWith("/dashboard?registration=pending&server=srv");
  });

  it("serializes delegated client auth separately from execution auth", async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText(/server id/i), { target: { value: "srv" } });
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: "Owned Server" } });
    fireEvent.change(screen.getByLabelText(/^server url$/i), { target: { value: "https://provider.test/mcp" } });
    fireEvent.change(screen.getByLabelText(/oauth provider key/i), { target: { value: "github" } });
    fireEvent.change(screen.getByLabelText(/required oauth scopes/i), {
      target: { value: "repo\nissues:write" },
    });
    fireEvent.change(screen.getByLabelText(/scope mode/i), { target: { value: "override" } });

    fireEvent.click(screen.getByRole("button", { name: /fetch metadata/i }));

    await waitFor(() => {
      expect(discoverProviderServerMetadata).toHaveBeenCalledWith("access-token-123", {
        server_id: "srv",
        url: "https://provider.test/mcp",
        execution_auth: { auth_type: "none" },
      });
    });

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /review tool metadata/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /continue to published metadata/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /edit published metadata/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /continue to confirmation/i }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /confirm registration/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /register server/i }));

    await waitFor(() => {
      expect(registerProviderServer).toHaveBeenCalledWith(
        "access-token-123",
        expect.objectContaining({
          execution_auth: { auth_type: "none" },
          client_auth: {
            provider_key: "github",
            required_scopes: ["repo", "issues:write"],
            scope_mode: "override",
          },
        }),
      );
    });
  });

  it("skips the hosted-connect probe when the feature flag is off", async () => {
    configFlags.hostedConnectEnabled = false;
    renderPage();

    fireEvent.change(screen.getByLabelText(/server id/i), { target: { value: "srv" } });
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: "Owned Server" } });
    fireEvent.change(screen.getByLabelText(/^server url$/i), { target: { value: "https://provider.test/mcp" } });

    fireEvent.click(screen.getByRole("button", { name: /fetch metadata/i }));

    await waitFor(() => {
      expect(discoverProviderServerMetadata).toHaveBeenCalled();
    });
    expect(discoverProviderConnect).not.toHaveBeenCalled();
  });

  it("falls through to standard discovery when the hosted-connect probe throws", async () => {
    discoverProviderConnect.mockRejectedValue(new Error("network: connect route not deployed"));
    renderPage();

    fireEvent.change(screen.getByLabelText(/server id/i), { target: { value: "srv" } });
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: "Owned Server" } });
    fireEvent.change(screen.getByLabelText(/^server url$/i), { target: { value: "https://provider.test/mcp" } });

    fireEvent.click(screen.getByRole("button", { name: /fetch metadata/i }));

    await waitFor(() => {
      expect(discoverProviderServerMetadata).toHaveBeenCalled();
    });
    expect(discoverProviderConnect).toHaveBeenCalled();
  });
});
