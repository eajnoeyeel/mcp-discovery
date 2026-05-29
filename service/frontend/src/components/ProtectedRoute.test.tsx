import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const authMock = vi.hoisted(() => ({
  useAuth: vi.fn(),
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: authMock.useAuth,
}));

import ProtectedRoute from './ProtectedRoute';

function LoginProbe() {
  const location = useLocation();
  return <div data-testid="login-location">{`${location.pathname}${location.search}${location.hash}`}</div>;
}

function renderRoute(initialPath: string = '/dashboard') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <div>Protected content</div>
            </ProtectedRoute>
          }
        />
        <Route
          path="/connect"
          element={
            <ProtectedRoute>
              <div>Connect content</div>
            </ProtectedRoute>
          }
        />
        <Route path="/login" element={<LoginProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('ProtectedRoute', () => {
  it('redirects unauthenticated users to /login with redirect param', () => {
    authMock.useAuth.mockReturnValue({ session: null, loading: false });

    renderRoute();

    const location = screen.getByTestId('login-location').textContent ?? '';
    expect(location.startsWith('/login?redirect=')).toBe(true);
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
  });

  it('renders children when the user has an active session', () => {
    authMock.useAuth.mockReturnValue({
      session: { user: { id: 'user-123' } },
      loading: false,
    });

    renderRoute();

    expect(screen.getByText('Protected content')).toBeInTheDocument();
    expect(screen.queryByTestId('login-location')).not.toBeInTheDocument();
  });

  it('shows the loading spinner while auth state is resolving', () => {
    authMock.useAuth.mockReturnValue({ session: null, loading: true });

    const { container } = renderRoute();

    expect(screen.queryByText('Protected content')).not.toBeInTheDocument();
    expect(screen.queryByTestId('login-location')).not.toBeInTheDocument();
    expect(container.querySelector('.animate-spin')).toBeInTheDocument();
  });

  it('preserves query string when redirecting to /login', () => {
    authMock.useAuth.mockReturnValue({ session: null, loading: false });

    renderRoute('/connect?session=abc%3D%3D&state=xyz');

    const locationText = screen.getByTestId('login-location').textContent ?? '';
    const search = locationText.slice(locationText.indexOf('?'));
    const params = new URLSearchParams(search);
    const redirect = params.get('redirect') ?? '';
    expect(redirect).toBe('/connect?session=abc%3D%3D&state=xyz');
  });

  it('preserves hash fragment when redirecting to /login', () => {
    authMock.useAuth.mockReturnValue({ session: null, loading: false });

    renderRoute('/dashboard#tab=servers');

    const locationText = screen.getByTestId('login-location').textContent ?? '';
    const search = locationText.slice(locationText.indexOf('?'));
    const params = new URLSearchParams(search);
    const redirect = params.get('redirect') ?? '';
    expect(redirect).toBe('/dashboard#tab=servers');
  });

  it('preserves query string + hash together when redirecting', () => {
    authMock.useAuth.mockReturnValue({ session: null, loading: false });

    renderRoute('/connect?resume_token=abc%3D%3D#step=2');

    const locationText = screen.getByTestId('login-location').textContent ?? '';
    const search = locationText.slice(locationText.indexOf('?'));
    const params = new URLSearchParams(search);
    const redirect = params.get('redirect') ?? '';
    expect(redirect).toBe('/connect?resume_token=abc%3D%3D#step=2');
  });
});
