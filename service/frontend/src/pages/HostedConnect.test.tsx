import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const navigate = vi.fn();
const createClientConnectSession = vi.fn();
const openWindow = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    session: { access_token: 'access-token-123' },
    user: { id: 'user-123' },
    loading: false,
  }),
}));

vi.mock('@/lib/api', () => ({
  createClientConnectSession: (...args: unknown[]) => createClientConnectSession(...args),
}));

import HostedConnect from './HostedConnect';

function renderPage(initialEntry: string = '/connect?actor=client&provider=apify&server_id=srv&tool_name=lookup&tool_id=srv%3A%3Alookup&pending_execution_id=pending-123&resume_token=resume-123') {
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
          <Route path="/connect" element={<HostedConnect />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('HostedConnect page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('open', openWindow);
    createClientConnectSession.mockResolvedValue({
      connect_session_id: 'connect-123',
      actor_type: 'client',
      end_user_id: 'user-123',
      client_app_id: null,
      server_id: 'srv',
      tool_name: 'lookup',
      auth_type: 'oauth',
      status: 'awaiting_user_approval',
      scope: { reuse_scope: 'user', client_app_id: null },
    });
  });

  it('shows user-global versus client-app scope choices on the hosted connect page', () => {
    renderPage();

    expect(screen.getByLabelText(/Reuse across all my MLP clients/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Only this client app/i)).toBeInTheDocument();
  });

  it('shows a blocked message when client OAuth has no start_url', async () => {
    renderPage();

    fireEvent.click(screen.getByRole('button', { name: /start hosted connect/i }));

    await waitFor(() => {
      expect(createClientConnectSession).toHaveBeenCalledWith('access-token-123', {
        provider_key: 'apify',
        server_id: 'srv',
        tool_name: 'lookup',
        tool_id: 'srv::lookup',
        client_app_id: undefined,
        auth_type: 'oauth',
        pending_execution_id: 'pending-123',
      });
    });

    expect(openWindow).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/Hosted approval URL unavailable\. Client OAuth cannot continue until the backend returns a start_url\./i),
    ).toBeInTheDocument();
  });

  it('uses start_url and exposes the completion step when client OAuth approval URL is present', async () => {
    createClientConnectSession.mockResolvedValueOnce({
      connect_session_id: 'connect-123',
      actor_type: 'client',
      end_user_id: 'user-123',
      client_app_id: null,
      server_id: 'srv',
      tool_name: 'lookup',
      auth_type: 'oauth',
      status: 'awaiting_user_approval',
      scope: { reuse_scope: 'user', client_app_id: null },
      start_url: 'https://provider.test/oauth/start',
    });

    renderPage();

    fireEvent.click(screen.getByRole('button', { name: /start hosted connect/i }));

    await waitFor(() => {
      expect(openWindow).toHaveBeenCalledWith(
        'https://provider.test/oauth/start',
        '_blank',
        'noopener,noreferrer',
      );
    });
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByRole('link', { name: /Open hosted approval/i })).toHaveAttribute(
      'href',
      'https://provider.test/oauth/start',
    );
    expect(screen.getByRole('link', { name: /Continue to completion/i })).toHaveAttribute(
      'href',
      expect.stringContaining('/connect/complete?'),
    );
  });

  it('shows client API-key hosted connect as unavailable instead of a resumable flow', () => {
    renderPage('/connect?actor=client&server_id=srv&tool_name=lookup&auth_type=api_key&resume_token=resume-123');

    expect(screen.getByText(/Client API-key hosted connect is not available yet/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/API key header name/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Continue to completion/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Start hosted connect/i })).not.toBeInTheDocument();
  });

  it('shows provider API-key hosted connect as an unavailable shell', () => {
    renderPage('/connect?actor=provider&server_id=srv&tool_name=lookup&auth_type=api_key&return_to=%2Fdashboard%2Fregister');

    expect(screen.getByText(/Provider API-key hosted connect is not available yet/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/API key header name/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Continue to completion/i })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Return to registration/i })).toHaveAttribute('href', '/dashboard/register');
  });

  it('carries provider oauth state into the validation shell link', () => {
    renderPage('/connect?actor=provider&server_id=srv&tool_name=lookup&auth_type=oauth&session=connect-123&start_url=https%3A%2F%2Fprovider.test%2Foauth%2Fstart%3Fstate%3Doauth-state-123&return_to=%2Fdashboard%2Fregister');

    expect(screen.getByRole('link', { name: /Continue to validation shell/i })).toHaveAttribute(
      'href',
      expect.stringContaining('state=oauth-state-123'),
    );
  });
});
