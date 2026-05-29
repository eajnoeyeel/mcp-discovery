import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const navigate = vi.fn();
const discoverProviderConnect = vi.fn();
const discoverProviderServerMetadata = vi.fn();
const registerProviderServer = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

vi.mock('@/lib/config', () => ({
  config: {
    api: { isConfigured: true, url: 'http://api.test', key: 'test-key' },
    supabase: { isConfigured: true, url: 'http://supabase.test', anonKey: 'anon' },
    hostedConnect: { enabled: true },
  },
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    session: { access_token: 'access-token-123' },
    user: { id: 'user-123' },
    loading: false,
  }),
}));

vi.mock('@/lib/api', () => ({
  discoverProviderConnect: (...args: unknown[]) => discoverProviderConnect(...args),
  discoverProviderServerMetadata: (...args: unknown[]) => discoverProviderServerMetadata(...args),
  registerProviderServer: (...args: unknown[]) => registerProviderServer(...args),
}));

import RegisterServer from './RegisterServer';

const PROVIDER_CONNECT_DRAFT_STORAGE_KEY = 'mlp:provider-connect-registration-draft';

function renderPage(initialEntry: string = '/dashboard/register') {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/dashboard/register" element={<RegisterServer />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('RegisterServer hosted auth branch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    discoverProviderConnect.mockResolvedValue({
      connect_session_id: 'connect-123',
      provider_user_id: 'user-123',
      server_id: 'srv',
      url: 'https://provider.test/mcp',
      auth_type: 'oauth',
      start_url: 'https://provider.test/oauth/start',
      status: 'awaiting_provider_approval',
    });
    discoverProviderServerMetadata.mockResolvedValue({
      url: 'https://provider.test/mcp',
      tools: [
        {
          tool_name: 'lookup',
          upstream_description: 'Lookup docs',
          input_schema: null,
          parameter_metadata: [],
        },
      ],
      warnings: [],
    });
    registerProviderServer.mockResolvedValue({
      server_id: 'srv',
      tools_count: 1,
      message: 'Server registered. Indexing in progress.',
    });
  });

  it('branches into hosted connect before metadata fetch when provider auth is required', async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText(/server id/i), { target: { value: 'srv' } });
    fireEvent.change(screen.getByLabelText(/server name/i), { target: { value: 'Owned Server' } });
    fireEvent.change(screen.getByLabelText(/^server url$/i), { target: { value: 'https://provider.test/mcp' } });
    fireEvent.change(screen.getByLabelText(/description/i), { target: { value: 'Owned search MCP' } });
    fireEvent.change(screen.getByLabelText(/tags/i), { target: { value: 'search, docs' } });
    fireEvent.change(screen.getByLabelText(/auth type/i), { target: { value: 'oauth_session' } });
    fireEvent.change(screen.getByLabelText(/oauth token endpoint/i), {
      target: { value: 'https://provider.test/oauth/token' },
    });
    fireEvent.change(screen.getByLabelText(/oauth client id/i), { target: { value: 'client-id-123' } });
    fireEvent.change(screen.getByLabelText(/oauth client secret/i), { target: { value: 'client-secret-123' } });
    fireEvent.change(screen.getByLabelText(/oauth refresh token/i), { target: { value: 'refresh-token-123' } });
    fireEvent.change(screen.getByLabelText(/oauth provider key/i), { target: { value: 'github' } });
    fireEvent.change(screen.getByLabelText(/required oauth scopes/i), {
      target: { value: 'repo\nissues:write' },
    });
    fireEvent.change(screen.getByLabelText(/scope mode/i), { target: { value: 'override' } });
    fireEvent.change(screen.getByLabelText(/auth type/i), { target: { value: 'none' } });

    fireEvent.click(screen.getByRole('button', { name: /fetch metadata/i }));

    await waitFor(() => {
      expect(discoverProviderConnect).toHaveBeenCalledWith('access-token-123', {
        server_id: 'srv',
        url: 'https://provider.test/mcp',
      });
    });

    expect(navigate).toHaveBeenCalledWith(expect.stringContaining('/connect?'));
    expect(navigate).toHaveBeenCalledWith(expect.stringContaining('actor=provider'));
    expect(discoverProviderServerMetadata).not.toHaveBeenCalled();
    const persistedDraft = JSON.parse(sessionStorage.getItem(PROVIDER_CONNECT_DRAFT_STORAGE_KEY) ?? '{}');
    expect(persistedDraft).toMatchObject({
      serverId: 'srv',
      name: 'Owned Server',
      url: 'https://provider.test/mcp',
      description: 'Owned search MCP',
      tags: 'search, docs',
      authType: 'none',
      clientAuthProviderKey: 'github',
      clientAuthRequiredScopes: 'repo\nissues:write',
      clientAuthScopeMode: 'override',
    });
    expect(persistedDraft.oauthClientSecret).toBeUndefined();
    expect(persistedDraft.oauthRefreshToken).toBeUndefined();
    expect(persistedDraft.oauthTokenEndpoint).toBeUndefined();
    expect(persistedDraft.oauthClientId).toBeUndefined();
    expect(persistedDraft.bearerToken).toBeUndefined();
    expect(persistedDraft.apiKey).toBeUndefined();
  });

  it('resumes metadata discovery after returning from hosted connect', async () => {
    sessionStorage.setItem(
      PROVIDER_CONNECT_DRAFT_STORAGE_KEY,
      JSON.stringify({
        serverId: 'srv',
        name: 'Owned Server',
        url: 'https://provider.test/mcp',
        description: '',
        tags: '',
        authType: 'none',
      }),
    );

    renderPage('/dashboard/register?providerConnect=connected&serverId=srv');

    await waitFor(() => {
      expect(discoverProviderServerMetadata).toHaveBeenCalledWith('access-token-123', {
        server_id: 'srv',
        url: 'https://provider.test/mcp',
        execution_auth: { auth_type: 'none' },
      });
    });

    expect(await screen.findByRole('heading', { name: /review tool metadata/i })).toBeInTheDocument();
  });

  it('restores the sanitized draft after returning from the provider validation shell', async () => {
    sessionStorage.setItem(
      PROVIDER_CONNECT_DRAFT_STORAGE_KEY,
      JSON.stringify({
        serverId: 'srv',
        name: 'Owned Server',
        url: 'https://provider.test/mcp',
        description: 'Owned search MCP',
        tags: 'search, docs',
        authType: 'none',
        clientAuthProviderKey: 'github',
        clientAuthRequiredScopes: 'repo\nissues:write',
        clientAuthScopeMode: 'override',
      }),
    );

    renderPage('/dashboard/register?providerConnect=shell&serverId=srv');

    expect(await screen.findByDisplayValue('srv')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Owned Server')).toBeInTheDocument();
    expect(screen.getByDisplayValue('https://provider.test/mcp')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Owned search MCP')).toBeInTheDocument();
    expect(screen.getByDisplayValue('search, docs')).toBeInTheDocument();
    expect(screen.getByLabelText(/oauth provider key/i)).toHaveValue('github');
    expect(screen.getByLabelText(/required oauth scopes/i)).toHaveValue('repo\nissues:write');
    expect(screen.getByLabelText(/scope mode/i)).toHaveValue('override');
    expect(screen.getByText(/browser-based provider finalize is not available yet/i)).toBeInTheDocument();
    expect(discoverProviderServerMetadata).not.toHaveBeenCalled();
  });

  it('strips sensitive auth fields from legacy drafts during restore', async () => {
    sessionStorage.setItem(
      PROVIDER_CONNECT_DRAFT_STORAGE_KEY,
      JSON.stringify({
        serverId: 'srv',
        name: 'Owned Server',
        url: 'https://provider.test/mcp',
        description: 'Owned search MCP',
        tags: 'search, docs',
        authType: 'oauth_session',
        bearerToken: 'legacy-bearer-token',
        apiKeyHeaderName: 'x-provider-key',
        apiKey: 'legacy-api-key',
        customHeadersText: 'x-team-id: provider-123',
        oauthTokenEndpoint: 'https://provider.test/oauth/token',
        oauthClientId: 'legacy-client-id',
        oauthClientSecret: 'legacy-client-secret',
        oauthRefreshToken: 'legacy-refresh-token',
        oauthScope: 'tools.execute',
        clientAuthProviderKey: 'github',
        clientAuthRequiredScopes: 'repo\nissues:write',
        clientAuthScopeMode: 'override',
      }),
    );

    renderPage('/dashboard/register?providerConnect=shell&serverId=srv');

    expect(await screen.findByDisplayValue('srv')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Owned Server')).toBeInTheDocument();
    expect(screen.getByDisplayValue('https://provider.test/mcp')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Owned search MCP')).toBeInTheDocument();
    expect(screen.getByDisplayValue('search, docs')).toBeInTheDocument();
    expect(screen.getByLabelText(/oauth provider key/i)).toHaveValue('github');
    expect(screen.getByLabelText(/required oauth scopes/i)).toHaveValue('repo\nissues:write');
    expect(screen.getByLabelText(/scope mode/i)).toHaveValue('override');
    expect(screen.getByLabelText(/auth type/i)).toHaveValue('oauth_session');
    expect(screen.getByLabelText(/oauth token endpoint/i)).toHaveValue('');
    expect(screen.getByLabelText(/oauth client id/i)).toHaveValue('');
    expect(screen.getByLabelText(/oauth client secret/i)).toHaveValue('');
    expect(screen.getByLabelText(/oauth refresh token/i)).toHaveValue('');
    expect(screen.getByLabelText(/^oauth scope$/i)).toHaveValue('');

    fireEvent.change(screen.getByLabelText(/auth type/i), { target: { value: 'bearer' } });
    expect(screen.getByLabelText(/bearer token/i)).toHaveValue('');

    fireEvent.change(screen.getByLabelText(/auth type/i), { target: { value: 'api_key_header' } });
    expect(screen.getByLabelText(/api key header name/i)).toHaveValue('');
    expect(screen.getByLabelText(/^api key$/i)).toHaveValue('');

    fireEvent.change(screen.getByLabelText(/auth type/i), { target: { value: 'custom_headers' } });
    expect(screen.getByLabelText(/custom headers/i)).toHaveValue('');
  });
});
