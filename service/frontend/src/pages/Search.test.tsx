import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/config', () => ({
  config: {
    api: { isConfigured: true, url: 'http://api.test', key: 'test-key' },
    supabase: { isConfigured: true, url: 'http://supabase.test', anonKey: 'anon' },
  },
}));

vi.mock('@/lib/api', () => ({
  getPlatformStats: vi.fn(),
  searchTools: vi.fn(),
}));

import { getPlatformStats, searchTools } from '@/lib/api';
import SearchPage from './Search';

const mockedSearchTools = vi.mocked(searchTools);
const mockedGetPlatformStats = vi.mocked(getPlatformStats);

function renderPage(initialQuery: string = '?q=docs') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/search${initialQuery}`]}>
        <Routes>
          <Route path="/search" element={<SearchPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SearchPage degraded contract', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetPlatformStats.mockResolvedValue({
      server_count: 5,
      tool_count: 50,
      indexed_count: 50,
      avg_geo_score: 0.7,
    });
  });

  it('renders a Degraded badge when the backend reports degraded results', async () => {
    mockedSearchTools.mockResolvedValue({
      query: 'docs',
      results: [],
      strategy: 'flat',
      latency_ms: 42,
      degraded: true,
      confidence: 0.31,
    });

    renderPage('?q=docs');

    await waitFor(() => {
      expect(screen.getByLabelText(/search is degraded/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/confidence 0\.31/i)).toBeInTheDocument();
  });

  it('omits the Degraded badge when the backend does not set degraded', async () => {
    mockedSearchTools.mockResolvedValue({
      query: 'docs',
      results: [],
      strategy: 'flat',
      latency_ms: 42,
    });

    renderPage('?q=docs');

    await waitFor(() => {
      expect(screen.getByText(/found 0 results/i)).toBeInTheDocument();
    });
    expect(screen.queryByLabelText(/search is degraded/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
  });
});
