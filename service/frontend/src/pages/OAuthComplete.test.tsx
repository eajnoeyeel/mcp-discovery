import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    session: { access_token: 'access-token-123' },
    user: { id: 'user-123' },
    loading: false,
  }),
}));

describe('OAuthComplete page', () => {
  const assign = vi.fn();

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ code: 'issued-code-123' }),
      }),
    );
    Object.defineProperty(window, 'location', {
      value: { assign },
      writable: true,
    });
  });

  it('issues a local dev code and redirects back to the MCP callback url', async () => {
    const OAuthComplete = (await import('./OAuthComplete')).default;

    render(
      <MemoryRouter initialEntries={['/oauth/complete?redirect_uri=http%3A%2F%2Flocalhost%3A9999%2Fcallback&state=test-state']}>
        <Routes>
          <Route path="/oauth/complete" element={<OAuthComplete />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText(/Completing sign-in/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:8080/oauth/issue-code',
        expect.objectContaining({
          method: 'POST',
          headers: { authorization: 'Bearer access-token-123' },
        }),
      );
    });

    await waitFor(() => {
      expect(assign).toHaveBeenCalledWith(
        'http://localhost:9999/callback?code=issued-code-123&state=test-state',
      );
    });
  });
});
