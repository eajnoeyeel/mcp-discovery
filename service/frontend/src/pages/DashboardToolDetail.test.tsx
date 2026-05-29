import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/config', () => ({
  config: {
    api: { isConfigured: true, url: 'http://api.test', key: 'test-key' },
    supabase: { isConfigured: true, url: 'http://supabase.test', anonKey: 'anon' },
  },
}));

vi.mock('@/lib/api', () => ({
  getProviderToolDetail: vi.fn(),
  getToolAnalytics: vi.fn(),
  getToolInsights: vi.fn(),
  updateProviderToolMetadata: vi.fn(),
  previewProviderToolMetadataRefresh: vi.fn(),
  applyProviderToolMetadataRefresh: vi.fn(),
}));

const authState = {
  session: { access_token: 'access-token-123' },
  user: { id: 'user-123' },
  loading: false,
};

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => authState,
}));

vi.mock('@/components/GEOScoreRadar', () => ({
  default: ({ geoScore }: { geoScore: { total: number } }) => (
    <div>Mock radar {(geoScore.total * 100).toFixed(0)}</div>
  ),
}));

import {
  applyProviderToolMetadataRefresh,
  getProviderToolDetail,
  getToolAnalytics,
  getToolInsights,
  previewProviderToolMetadataRefresh,
  updateProviderToolMetadata,
} from '@/lib/api';
import DashboardToolDetail from './DashboardToolDetail';


const mockedGetProviderToolDetail = vi.mocked(getProviderToolDetail);
const mockedGetToolAnalytics = vi.mocked(getToolAnalytics);
const mockedGetToolInsights = vi.mocked(getToolInsights);
const mockedUpdateProviderToolMetadata = vi.mocked(updateProviderToolMetadata);
const mockedPreviewProviderToolMetadataRefresh = vi.mocked(previewProviderToolMetadataRefresh);
const mockedApplyProviderToolMetadataRefresh = vi.mocked(applyProviderToolMetadataRefresh);

function buildToolDetail(overrides: Record<string, unknown> = {}) {
  return {
    tool: {
      id: 'tool-row-1',
      tool_id: 'srv::lookup',
      tool_name: 'lookup',
      server_id: 'srv',
      server_name: 'Owned Server',
      description: 'Resolve a record by query.',
      upstream_description: 'Reference upstream copy.',
      parameter_notes: 'Use q for exact lookup.',
      usage_examples: ['{"q": "docs"}'],
      usage_hints: ['Exact identifiers only'],
      input_schema: null,
      index_status: 'indexed',
      created_at: '2026-04-12T00:00:00Z',
      geo_score: {
        total: 0.41,
        clarity: 0.66,
        disambiguation: 0.2,
        parameter_coverage: 0.28,
        boundary: 0.55,
        stats: 0.31,
        precision: 0.47,
      },
      ...overrides,
    },
    competitors: [],
    simulations: [],
  };
}

function renderPage(initialEntry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/dashboard/tools/:toolId" element={<DashboardToolDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('DashboardToolDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.session.access_token = 'access-token-123';
    authState.user.id = 'user-123';
    mockedGetToolAnalytics.mockResolvedValue({ daily_stats: [], client_stats: [] });
    mockedGetToolInsights.mockResolvedValue({ insights: [] });
  });

  it('shows provider-facing actionability for indexed low-score tools', async () => {
    mockedGetProviderToolDetail.mockResolvedValueOnce({
      tool: {
        id: 'tool-row-1',
        tool_id: 'srv::lookup',
        tool_name: 'lookup',
        server_id: 'srv',
        server_name: 'Owned Server',
        description: 'Resolve a record by query.',
        input_schema: null,
        index_status: 'indexed',
        created_at: '2026-04-12T00:00:00Z',
        geo_score: {
          total: 0.41,
          clarity: 0.66,
          disambiguation: 0.2,
          parameter_coverage: 0.28,
          boundary: 0.55,
          stats: 0.31,
          precision: 0.47,
        },
      },
      competitors: [
        {
          id: 'tool-row-2',
          tool_id: 'srv::batch_lookup',
          tool_name: 'batch_lookup',
          server_id: 'srv',
          server_name: 'Owned Server',
          description: 'Resolve records in bulk.',
          input_schema: null,
          index_status: 'indexed',
          created_at: '2026-04-12T00:00:00Z',
          geo_score: {
            total: 0.62,
            clarity: 0.68,
            disambiguation: 0.58,
            parameter_coverage: 0.64,
            boundary: 0.6,
            stats: 0.61,
            precision: 0.63,
          },
        },
      ],
      simulations: [
        {
          recommended_tool_id: 'srv::lookup',
          server_id: 'srv',
          query_count: 18,
          avg_confidence: 0.82,
          avg_latency_ms: 146.2,
          high_confidence_count: 11,
        },
      ],
    });

    renderPage('/dashboard/tools/srv::lookup');

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'lookup' })).toBeInTheDocument();
    });

    expect(screen.getByText('Needs attention now')).toBeInTheDocument();
    expect(screen.getByText('Weakest dimensions')).toBeInTheDocument();
    expect(screen.getByText('Simulation evidence')).toBeInTheDocument();
    expect(screen.getByText('18 logged searches')).toBeInTheDocument();
    expect(screen.getByText('Current published metadata')).toBeInTheDocument();
    expect(screen.getByText('Same-server comparison')).toBeInTheDocument();
    expect(screen.queryByText('Search Simulator')).not.toBeInTheDocument();

    const weakestSection = screen.getByText('Weakest dimensions').closest('section');
    expect(weakestSection).not.toBeNull();

    const weakestText = weakestSection?.textContent ?? '';
    const disambiguationIndex = weakestText.indexOf('Disambiguation');
    const parameterCoverageIndex = weakestText.indexOf('Parameter coverage');
    const statsIndex = weakestText.indexOf('Stats');

    expect(disambiguationIndex).toBeGreaterThanOrEqual(0);
    expect(parameterCoverageIndex).toBeGreaterThan(disambiguationIndex);
    expect(statsIndex).toBeGreaterThan(parameterCoverageIndex);

    expect(
      screen.getByText('Add contrastive wording about when this tool should win instead of nearby alternatives.'),
    ).toBeInTheDocument();
  });


  it('shows published vs upstream metadata and saves override edits', async () => {
    mockedGetProviderToolDetail.mockResolvedValue(
      buildToolDetail({
        description: 'Published copy',
        upstream_description: 'Upstream reference copy',
        parameter_notes: 'Use q',
        usage_examples: ['{"q": "docs"}'],
        usage_hints: ['Exact identifiers only'],
        geo_score: null,
      }),
    );
    mockedUpdateProviderToolMetadata.mockResolvedValue({
      tool_id: 'srv::lookup',
      description: 'Updated published copy',
      parameter_notes: 'Use query',
      usage_examples: ['{"query": "docs"}'],
      usage_hints: ['Use for curated docs'],
      metadata_origin: 'mixed',
    });

    renderPage('/dashboard/tools/srv::lookup');

    await waitFor(() => {
      expect(screen.getByText('Current published metadata')).toBeInTheDocument();
    });

    expect(screen.getByText('Upstream reference metadata')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Published copy')).toBeInTheDocument();
    expect(screen.getByText('Upstream reference copy')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Published description'), {
      target: { value: 'Updated published copy' },
    });
    fireEvent.change(screen.getByLabelText('Parameter notes'), {
      target: { value: 'Use query' },
    });
    fireEvent.change(screen.getByLabelText('Usage examples'), {
      target: { value: '{"query": "docs"}' },
    });
    fireEvent.change(screen.getByLabelText('Usage hints'), {
      target: { value: 'Use for curated docs' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save published metadata' }));

    await waitFor(() => {
      expect(mockedUpdateProviderToolMetadata).toHaveBeenCalledWith('access-token-123', 'srv::lookup', {
        description: 'Updated published copy',
        parameter_notes: 'Use query',
        usage_examples: ['{"query": "docs"}'],
        usage_hints: ['Use for curated docs'],
      });
    });
  });

  it('renders refresh diff actions and warning state for schema changes', async () => {
    mockedGetProviderToolDetail.mockResolvedValue(buildToolDetail({
      description: 'Published copy',
      upstream_description: 'Old upstream copy',
      input_schema: { type: 'object', properties: { q: { type: 'string' } } },
      geo_score: null,
    }));
    mockedPreviewProviderToolMetadataRefresh.mockResolvedValue({
      server_id: 'srv',
      warnings: ['Upstream auth metadata changed during discovery.'],
      changed: [
        {
          tool_name: 'lookup',
          change_type: 'changed',
          effective_description: 'Published copy',
          upstream_description: 'Fresh upstream copy',
          schema_changed: true,
          severity: 'warning',
        },
      ],
      added: [],
      removed: [],
    });
    mockedApplyProviderToolMetadataRefresh.mockResolvedValue({
      tool: buildToolDetail({ description: 'Published copy' }).tool,
      preview: { server_id: 'srv', changed: [], added: [], removed: [] },
    });

    renderPage('/dashboard/tools/srv::lookup');

    await waitFor(() => {
      expect(screen.getByText('Re-fetch upstream metadata')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Preview upstream diff' }));

    await waitFor(() => {
      expect(mockedPreviewProviderToolMetadataRefresh).toHaveBeenCalledWith('access-token-123', 'srv::lookup');
    });

    expect(screen.getAllByText('Schema warning')).toHaveLength(2);
    expect(screen.getByText(/Input schema changed upstream/)).toBeInTheDocument();
    expect(screen.getByText('Fresh upstream copy')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keep current published metadata' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Adopt upstream reference' })).toBeInTheDocument();
  });


  it('clears stale refresh preview state when the route tool changes', async () => {
    mockedGetProviderToolDetail
      .mockResolvedValueOnce(buildToolDetail({ tool_id: 'srv::lookup', tool_name: 'lookup', description: 'Published copy', geo_score: null }))
      .mockResolvedValueOnce(buildToolDetail({ tool_id: 'srv::other', tool_name: 'other-tool', description: 'Other published copy', upstream_description: 'Other upstream copy', geo_score: null }));
    mockedPreviewProviderToolMetadataRefresh.mockResolvedValue({
      server_id: 'srv',
      changed: [
        {
          tool_name: 'lookup',
          change_type: 'changed',
          effective_description: 'Published copy',
          upstream_description: 'Fresh upstream copy',
          schema_changed: true,
          severity: 'warning',
        },
      ],
      added: [],
      removed: [],
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/dashboard/tools/srv::lookup']}>
          <Routes>
            <Route
              path="/dashboard/tools/:toolId"
              element={<>
                <Link to="/dashboard/tools/srv::other">Switch tool</Link>
                <DashboardToolDetail />
              </>}
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'lookup' })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Preview upstream diff' }));

    await waitFor(() => {
      expect(screen.getByText('Fresh upstream copy')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('link', { name: 'Switch tool' }));

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'other-tool' })).toBeInTheDocument();
    });

    expect(screen.queryByText('Fresh upstream copy')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Keep current published metadata' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Adopt upstream reference' })).not.toBeInTheDocument();
  });

  it('refetches provider-private queries when auth identity changes', async () => {
    mockedGetProviderToolDetail
      .mockResolvedValueOnce(buildToolDetail({ description: 'First viewer copy', geo_score: null }))
      .mockResolvedValueOnce(buildToolDetail({ description: 'Second viewer copy', geo_score: null }));
    mockedGetToolAnalytics
      .mockResolvedValueOnce({ daily_stats: [], client_stats: [] })
      .mockResolvedValueOnce({ daily_stats: [], client_stats: [] });
    mockedGetToolInsights
      .mockResolvedValueOnce({ insights: [] })
      .mockResolvedValueOnce({ insights: [] });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const view = render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/dashboard/tools/srv::lookup']}>
          <Routes>
            <Route path="/dashboard/tools/:toolId" element={<DashboardToolDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(mockedGetProviderToolDetail).toHaveBeenCalledWith('access-token-123', 'srv::lookup');
    });
    await waitFor(() => {
      expect(mockedGetToolAnalytics).toHaveBeenCalledWith('srv::lookup', 'access-token-123');
      expect(mockedGetToolInsights).toHaveBeenCalledWith('srv::lookup', 'access-token-123');
    });

    authState.session.access_token = 'access-token-456';
    authState.user.id = 'user-456';

    view.rerender(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/dashboard/tools/srv::lookup']}>
          <Routes>
            <Route path="/dashboard/tools/:toolId" element={<DashboardToolDetail />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(mockedGetProviderToolDetail).toHaveBeenCalledTimes(2);
    });
    expect(mockedGetProviderToolDetail).toHaveBeenLastCalledWith('access-token-456', 'srv::lookup');
    expect(mockedGetToolAnalytics).toHaveBeenLastCalledWith('srv::lookup', 'access-token-456');
    expect(mockedGetToolInsights).toHaveBeenLastCalledWith('srv::lookup', 'access-token-456');
  });

  it('shows pending-state guidance when GEO score and evidence are not ready', async () => {
    mockedGetProviderToolDetail.mockResolvedValueOnce({
      tool: {
        id: 'tool-row-3',
        tool_id: 'srv::pending',
        tool_name: 'pending-tool',
        server_id: 'srv',
        server_name: 'Owned Server',
        description: 'Pending indexing.',
        input_schema: null,
        index_status: 'pending',
        created_at: '2026-04-12T00:00:00Z',
        geo_score: null,
      },
      competitors: [],
      simulations: [],
    });

    renderPage('/dashboard/tools/srv::pending');

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'pending-tool' })).toBeInTheDocument();
    });

    expect(screen.getByText('Indexing in progress')).toBeInTheDocument();
    expect(screen.getByText(/No same-server comparison tools yet/)).toBeInTheDocument();
    expect(
      screen.getByText(/Simulation evidence will appear after query logs accumulate/),
    ).toBeInTheDocument();
  });

  it('hides the hosted-connect CTA when the tool metadata says connect is unsupported', async () => {
    mockedGetProviderToolDetail.mockResolvedValueOnce(
      buildToolDetail({
        connect_supported: false,
        client_auth_mode: 'oauth',
        connection_reuse_scope: 'user',
        geo_score: null,
      }),
    );

    renderPage('/dashboard/tools/srv::lookup');

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'lookup' })).toBeInTheDocument();
    });

    expect(screen.queryByRole('link', { name: /Open hosted connect/i })).not.toBeInTheDocument();
  });

  it('preconfigures the hosted-connect CTA from auth policy metadata', async () => {
    mockedGetProviderToolDetail.mockResolvedValueOnce(
      buildToolDetail({
        connect_supported: true,
        client_auth_mode: 'api_key',
        connection_reuse_scope: 'client_app',
        geo_score: null,
      }),
    );

    renderPage('/dashboard/tools/srv::lookup');

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'lookup' })).toBeInTheDocument();
    });

    const link = screen.getByRole('link', { name: /Open API key connect shell/i });
    const href = link.getAttribute('href');
    expect(href).toBeTruthy();
    const target = new URL(href!, 'http://localhost');
    expect(target.pathname).toBe('/connect');
    expect(target.searchParams.get('actor')).toBe('client');
    expect(target.searchParams.get('server_id')).toBe('srv');
    expect(target.searchParams.get('tool_name')).toBe('lookup');
    expect(target.searchParams.get('auth_type')).toBe('api_key');
    expect(target.searchParams.get('client_app_id')).toBe('dashboard-web');
    expect(target.searchParams.get('return_to')).toBe('/dashboard/tools/srv::lookup');
  });

  it('shows an error alert and hides the metadata editor when the detail query fails', async () => {
    mockedGetProviderToolDetail.mockRejectedValue(new Error('500 Internal Server Error'));
    mockedGetToolAnalytics.mockResolvedValue({});
    mockedGetToolInsights.mockResolvedValue({ insights: [] });

    renderPage('/dashboard/tools/srv::lookup');

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/failed to load tool/i);
    });
    expect(screen.getByRole('alert')).toHaveTextContent(/disabled/i);
    expect(screen.queryByLabelText(/published description/i)).not.toBeInTheDocument();
    expect(mockedUpdateProviderToolMetadata).not.toHaveBeenCalled();
  });
});
