import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const validateProviderConnectCallback = vi.fn();
const completeProviderConnect = vi.fn();
const resumePendingExecution = vi.fn();

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    session: { access_token: 'access-token-123' },
    user: { id: 'user-123' },
    loading: false,
  }),
}));

vi.mock('@/lib/api', () => ({
  validateProviderConnectCallback: (...args: unknown[]) => validateProviderConnectCallback(...args),
  completeProviderConnect: (...args: unknown[]) => completeProviderConnect(...args),
  resumePendingExecution: (...args: unknown[]) => resumePendingExecution(...args),
}));

import ConnectComplete from './ConnectComplete';

function renderPage(initialEntry: string, hash: string = '') {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  window.location.hash = hash;

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/connect/complete" element={<ConnectComplete />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ConnectComplete page', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.location.hash = '';
    validateProviderConnectCallback.mockResolvedValue({
      connect_session_id: 'connect-123',
      provider_user_id: 'provider-123',
      server_id: 'srv',
      url: 'https://provider.test/mcp',
      auth_type: 'oauth',
      callback_received_at: '2026-04-17T02:00:00Z',
      status: 'awaiting_provider_approval',
    });
  });

  it('keeps provider completion in validation-shell mode instead of offering browser finalize', async () => {
    renderPage(
      '/connect/complete?actor=provider&session=connect-123&server_id=srv&state=oauth-state&return_to=%2Fdashboard%2Fregister',
      '#access_token=browser-token',
    );

    await waitFor(() => {
      expect(validateProviderConnectCallback).toHaveBeenCalledWith(
        'access-token-123',
        expect.any(URLSearchParams),
      );
    });

    expect(screen.getByText(/cannot finalize a provider connection in the browser/i)).toBeInTheDocument();
    expect(screen.getByText(/ignored any browser-returned token material/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Finalize provider connect/i })).not.toBeInTheDocument();
    expect(completeProviderConnect).not.toHaveBeenCalled();

    const returnLink = screen.getByRole('link', { name: /Return to registration/i });
    expect(returnLink).toHaveAttribute('href', '/dashboard/register?providerConnect=shell&serverId=srv');
  });

  it('shows client API-key completion as non-resumable shell state', () => {
    renderPage('/connect/complete?actor=client&server_id=srv&tool_name=lookup&auth_type=api_key&resume_token=resume-123&api_key_captured=1');

    expect(screen.getByText(/Client API-key hosted connect is still a shell-only flow/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Resume pending action/i })).not.toBeInTheDocument();
  });
});
