import { test, expect } from '@playwright/test';

test.describe('Landing page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('hero section is visible with headline and CTAs', async ({ page }) => {
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('link', { name: /search tools/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /browse registry/i })).toBeVisible();
  });

  test('search bar is present on landing', async ({ page }) => {
    const searchInput = page.getByRole('textbox');
    await expect(searchInput.first()).toBeVisible();
  });

  test('feature cards are rendered (3 cards)', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Semantic Search' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'GEO Score Diagnostics' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'MCP Bridge' })).toBeVisible();
  });

  test('stat pills are visible', async ({ page }) => {
    // Either live counts or fallback strings should be shown
    await expect(page.getByText(/servers/i).first()).toBeVisible();
    await expect(page.getByText(/tools/i).first()).toBeVisible();
  });

  test('footer is visible', async ({ page }) => {
    await expect(page.getByText(/MCP Discovery Platform/i)).toBeVisible();
  });

  test('no browser console errors on load', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(msg.text());
    });
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    const fatal = errors.filter(
      (e) =>
        !e.includes('favicon') &&
        !e.includes('net::ERR_') &&
        !e.includes('403') &&
        !e.includes('Failed to load resource'),
    );
    expect(fatal).toHaveLength(0);
  });
});
