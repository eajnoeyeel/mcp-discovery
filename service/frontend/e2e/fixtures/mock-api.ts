/**
 * Playwright route mock helpers — API 응답을 가로채서 테스트용 데이터 반환.
 * 403/500 등 백엔드 의존성 없이 프론트엔드 플로우를 검증한다.
 */
import type { Page } from '@playwright/test';

export const API_PATTERN = '**/api';

export const MOCK_TOOL_ID = 'github-mcp-server::search_repositories';
export const MOCK_SERVER_ID = 'github-mcp-server';

export const mockDashboard = {
  tools: [
    {
      tool_id: MOCK_TOOL_ID,
      server_id: MOCK_SERVER_ID,
      tool_name: 'search_repositories',
      description: 'Search GitHub repositories by keyword',
      status: 'indexed',
      geo_score: { total: 0.82, clarity: 0.9, disambiguation: 0.8, parameter_coverage: 0.85, boundary: 0.75, stats: 0.8, precision: 0.82 },
    },
    {
      tool_id: 'github-mcp-server::create_issue',
      server_id: MOCK_SERVER_ID,
      tool_name: 'create_issue',
      description: 'Create a new issue in a GitHub repository',
      status: 'indexed',
      geo_score: { total: 0.45, clarity: 0.5, disambiguation: 0.4, parameter_coverage: 0.4, boundary: 0.5, stats: 0.4, precision: 0.5 },
    },
  ],
  summary: { total_tools: 2, avg_geo_score: 0.635, needs_improvement: 1, indexed_count: 2 },
};

export const mockToolDetail = {
  tool: {
    tool_id: MOCK_TOOL_ID,
    server_id: MOCK_SERVER_ID,
    tool_name: 'search_repositories',
    description: 'Search GitHub repositories by keyword',
    upstream_description: 'Search GitHub repositories',
    status: 'indexed',
    index_status: 'indexed',
    geo_score: { total: 0.82, clarity: 0.9, disambiguation: 0.8, parameter_coverage: 0.85, boundary: 0.75, stats: 0.8, precision: 0.82 },
    input_schema: { type: 'object', properties: { query: { type: 'string', description: 'Search query' } }, required: ['query'] },
    parameter_metadata: [{ name: 'query', description: 'Search query', type: 'string' }],
    published_parameter_metadata: [],
    connect_supported: false,
    client_auth_mode: null,
  },
  competitors: [],
  simulations: [],
};

export const mockDiscovery = {
  server_id: 'test-server-e2e',
  name: 'Test MCP Server',
  description: 'A test MCP server for E2E validation',
  url: 'https://example.com/mcp',
  tools: [
    {
      tool_name: 'hello_world',
      description: 'Returns hello world',
      upstream_description: 'Returns hello world',
      input_schema: { type: 'object', properties: { name: { type: 'string' } } },
      parameter_metadata: [],
      published_parameter_metadata: [],
      parameter_notes: '',
      usage_examples: [],
      usage_hints: [],
    },
  ],
  auth_type: 'none',
};

export const mockRegisterResponse = {
  server_id: 'test-server-e2e',
  status: 'pending',
  message: 'Server registered successfully. Indexing in progress.',
};

export const mockInsights = {
  total_calls: 142,
  success_rate: 0.94,
  avg_latency_ms: 320,
  top_tools: [{ tool_name: 'search_repositories', calls: 98 }],
};

/**
 * 모든 API 엔드포인트를 mock으로 교체한다.
 */
export async function mockAllApis(page: Page) {
  // Dashboard
  await page.route(`${API_PATTERN}/providers/dashboard`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDashboard) }),
  );

  // Provider profile
  await page.route(`${API_PATTERN}/providers/profile`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ provider_id: 'test', name: '이연재' }) }),
  );

  // Tool detail
  await page.route(`${API_PATTERN}/providers/tools/**`, (route) => {
    const { pathname } = new URL(route.request().url());
    const method = route.request().method();

    if (pathname.endsWith('/insights')) {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockInsights) });
      return;
    }

    if (pathname.endsWith('/metadata-refresh-preview')) {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ has_changes: false, diffs: [] }),
      });
      return;
    }

    if (method === 'PUT') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
      return;
    }

    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockToolDetail) });
  });

  // Discovery
  await page.route(`${API_PATTERN}/providers/servers/discovery`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(mockDiscovery) }),
  );

  // Register server
  await page.route(`${API_PATTERN}/servers`, (route) => {
    if (route.request().method() === 'POST') {
      route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(mockRegisterResponse) });
    } else {
      route.continue();
    }
  });

  // Platform stats
  await page.route(`${API_PATTERN}/platform/stats`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ server_count: 290, tool_count: 2800 }) }),
  );

  // Search
  await page.route(`${API_PATTERN}/search`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ results: [], latency_ms: 50, strategy: 'flat', confidence: 0.0 }),
    }),
  );

}
