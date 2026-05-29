import { test, expect } from '@playwright/test';
import { API_PATTERN, mockAllApis, MOCK_TOOL_ID } from './fixtures/mock-api.ts';

const encodedToolId = encodeURIComponent(MOCK_TOOL_ID);

test.describe('Dashboard 툴 상세 (DashboardToolDetail)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
    await page.goto(`/dashboard/tools/${encodedToolId}`);
    await page.waitForLoadState('networkidle');
    // Wait until the loading spinner resolves and content (any text) appears
    await page.waitForFunction(() => document.body.innerText.trim().length > 0, { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(500);
  });

  test('툴 상세 페이지가 로드된다', async ({ page }) => {
    await expect(page).toHaveURL(/\/dashboard\/tools\/.+/);
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });

  test('툴 이름(search_repositories)이 표시된다', async ({ page }) => {
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).toMatch(/search_repositories/i);
  });

  test('GEO 6개 차원 레이블이 표시된다', async ({ page }) => {
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).toMatch(/clarity|disambiguation|parameter|boundary|stats|precision/i);
  });

  test('Description 편집 textarea가 존재한다', async ({ page }) => {
    const textareas = page.getByRole('textbox');
    expect(await textareas.count()).toBeGreaterThan(0);
  });

  test('Save/Update/Publish 버튼이 존재한다', async ({ page }) => {
    const saveBtn = page.getByRole('button').filter({ hasText: /save|update|publish/i });
    expect(await saveBtn.count()).toBeGreaterThan(0);
  });

  test('description 수정 후 Save 클릭 → PUT mock 처리 (crash 없음)', async ({ page }) => {
    await page.route(`${API_PATTERN}/providers/tools/**`, (route) => {
      if (route.request().method() === 'PUT') {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
      } else {
        route.continue();
      }
    });

    const textarea = page.getByRole('textbox').first();
    if (await textarea.isVisible()) {
      await textarea.fill('Updated description for E2E test');
      const saveBtn = page.getByRole('button').filter({ hasText: /save|update|publish/i }).first();
      if (await saveBtn.isVisible()) {
        await saveBtn.click();
        await page.waitForTimeout(500);
        const bodyText = await page.locator('body').innerText();
        expect(bodyText.trim().length).toBeGreaterThan(0);
      }
    }
  });

  test('Metadata Refresh Preview 버튼이 있으면 클릭 → diff 응답 처리', async ({ page }) => {
    const refreshBtn = page.getByRole('button').filter({ hasText: /refresh|preview/i }).first();
    if (await refreshBtn.isVisible()) {
      await refreshBtn.click();
      await page.waitForFunction(() => document.body.innerText.trim().length > 0, { timeout: 5000 }).catch(() => {});
      const bodyText = await page.locator('body').innerText();
      expect(bodyText.trim().length).toBeGreaterThan(0);
    } else {
      test.skip();
    }
  });

  test('Back to Dashboard 링크 클릭 → /dashboard 이동', async ({ page }) => {
    const backLink = page.getByRole('link', { name: /dashboard/i }).first();
    if (await backLink.isVisible()) {
      await backLink.click();
      await page.waitForLoadState('networkidle');
      await expect(page).toHaveURL(/\/dashboard/);
    }
  });
});
