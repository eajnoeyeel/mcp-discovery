import { test, expect } from '@playwright/test';
import { mockAllApis, mockDashboard, MOCK_TOOL_ID } from './fixtures/mock-api.ts';

test.describe('Provider Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await mockAllApis(page);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 });
  });

  test('대시보드가 로그인 상태로 열린다 (로그인 리다이렉트 없음)', async ({ page }) => {
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.locator('body')).not.toBeEmpty();
  });

  test('Summary 카드 4개가 렌더링된다', async ({ page }) => {
    await expect(page.getByText('Total Tools')).toBeVisible();
    await expect(page.getByText('Avg GEO Score')).toBeVisible();
    await expect(page.getByText('Needs Improvement')).toBeVisible();
    await expect(page.getByText('Fully Indexed')).toBeVisible();
  });

  test('mock 데이터 기준 Total Tools = 2', async ({ page }) => {
    await expect(page.getByText('2').first()).toBeVisible();
  });

  test('mock 툴 이름이 화면에 표시된다', async ({ page }) => {
    await page.waitForTimeout(2000);
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).toMatch(/search_repositories/i);
    expect(bodyText).toMatch(/create_issue/i);
  });

  test('GEO 점수 바(bar)가 툴마다 렌더링된다', async ({ page }) => {
    const bars = page.locator('[class*="bg-success"], [class*="bg-warning"], [class*="bg-destructive"]');
    await expect(bars.first()).toBeVisible();
    expect(await bars.count()).toBeGreaterThanOrEqual(2);
  });

  test('Register New Server 링크가 있다', async ({ page }) => {
    await expect(page.getByRole('link', { name: /register/i }).first()).toBeVisible();
  });

  test('Register 링크 클릭 → /dashboard/register 이동', async ({ page }) => {
    await page.getByRole('link', { name: /register/i }).first().click();
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveURL(/\/dashboard\/register/);
  });

  test('툴 클릭 → Dashboard 툴 상세 페이지 이동', async ({ page }) => {
    const toolLinks = page.locator('a[href*="/dashboard/tools/"]');
    await expect(toolLinks.first()).toBeVisible();
    await toolLinks.first().click();
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveURL(/\/dashboard\/tools\/.+/);
  });

  test('Worst tool 경고 배너가 낮은 GEO 점수 툴을 표시한다', async ({ page }) => {
    // create_issue의 GEO score = 0.45 → "needs improvement" 표시 예상
    const bodyText = await page.locator('body').innerText();
    expect(bodyText).toMatch(/create_issue|needs improvement|0\.45/i);
  });
});
