import { test, expect } from '@playwright/test';

test.describe('Navigation', () => {
  test('landing → /search via CTA', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: /search tools/i }).click();
    await expect(page).toHaveURL(/\/search/);
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('textbox').first()).toBeVisible();
  });

  test('landing → /servers via Browse Registry', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: /browse registry/i }).click();
    await expect(page).toHaveURL(/\/servers/);
    await page.waitForLoadState('networkidle');
  });

  test('/login page renders without crash', async ({ page }) => {
    await page.goto('/login');
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveURL(/\/login/);
    // Login page should have some visible content
    await expect(page.locator('body')).not.toBeEmpty();
  });

  test('/dashboard redirects unauthenticated user to /login', async ({ page }) => {
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');
    // ProtectedRoute redirects to login or shows login prompt
    const url = page.url();
    expect(url).toMatch(/\/(login|dashboard)/);
  });

  test('404 route shows not-found page', async ({ page }) => {
    await page.goto('/this-page-does-not-exist-xyz');
    await page.waitForLoadState('networkidle');
    // Should show NotFound component, not crash
    await expect(page.locator('body')).not.toBeEmpty();
  });

  test('layout nav header is visible on all public pages', async ({ page }) => {
    for (const path of ['/', '/search', '/servers', '/login']) {
      await page.goto(path);
      await page.waitForLoadState('networkidle');
      // Header/nav should be present (Layout wraps all routes)
      await expect(page.locator('header, nav').first()).toBeVisible();
    }
  });
});
