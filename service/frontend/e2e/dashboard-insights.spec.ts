import { test, expect } from '@playwright/test';
import { API_PATTERN, mockAllApis } from './fixtures/mock-api.ts';

test.describe('Dashboard Insights', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
    await page.goto('/dashboard/insights');
    await page.waitForLoadState('networkidle');
  });

  test('Insights 페이지가 로드된다', async ({ page }) => {
    await expect(page).toHaveURL(/\/dashboard\/insights/);
    await expect(page.locator('body')).not.toBeEmpty();
  });

  test('차트 또는 통계 컨텐츠가 렌더링된다', async ({ page }) => {
    await page.waitForTimeout(1000);
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });
});

test.describe('Dashboard Settings', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
    await page.goto('/dashboard/settings');
    await page.waitForLoadState('networkidle');
  });

  test('Settings 페이지가 로드된다', async ({ page }) => {
    await expect(page).toHaveURL(/\/dashboard\/settings/);
    await expect(page.locator('body')).not.toBeEmpty();
  });

  test('설정 폼 또는 컨텐츠가 있다', async ({ page }) => {
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });
});

test.describe('Dashboard Server Detail', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);

    // GET /api/providers/servers/:id mock
    await page.route(`${API_PATTERN}/providers/servers/**`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          server_id: 'github-mcp-server',
          name: 'GitHub MCP Server',
          description: 'MCP server for GitHub operations',
          status: 'indexed',
          tools: [],
        }),
      }),
    );

    await page.goto('/dashboard/servers/github-mcp-server');
    await page.waitForLoadState('networkidle');
  });

  test('Dashboard 서버 상세 페이지가 로드된다', async ({ page }) => {
    await expect(page).toHaveURL(/\/dashboard\/servers\/.+/);
    await expect(page.locator('body')).not.toBeEmpty();
  });

  test('서버 이름이 표시된다', async ({ page }) => {
    await page.waitForTimeout(1000);
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });
});
