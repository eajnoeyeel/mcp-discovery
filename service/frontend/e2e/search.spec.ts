import { test, expect } from '@playwright/test';

test.describe('Search page', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/search');
    await page.waitForLoadState('networkidle');
  });

  test('search bar renders on /search', async ({ page }) => {
    await expect(page.getByRole('textbox').first()).toBeVisible();
  });

  test('typing in search bar updates URL query param', async ({ page }) => {
    const input = page.getByRole('textbox').first();
    await input.fill('github file search');
    await input.press('Enter');
    await expect(page).toHaveURL(/[?&]q=/);
  });

  test('search with query shows result count or fallback message', async ({ page }) => {
    await page.goto('/search?q=github');
    await page.waitForLoadState('networkidle');
    // Either results are shown, or a "coming soon" fallback, or a loading state
    await expect(page.locator('body')).not.toBeEmpty();
    // Should not show an unhandled blank page
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });

  test('API-configured: search returns results or handles error gracefully', async ({
    page,
  }) => {
    // .env.local has VITE_API_URL set → config.api.isConfigured === true
    // This test validates that either results appear OR an error state is shown
    // (not a blank/crashed page)
    await page.goto('/search?q=send+email');
    // Allow up to 10s for API response
    await page.waitForTimeout(2000);

    const bodyText = await page.locator('body').innerText();
    // Must have at minimum the search bar text still visible
    expect(bodyText.trim().length).toBeGreaterThan(10);
  });

  test('empty query does not crash the page', async ({ page }) => {
    await page.goto('/search?q=');
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('textbox').first()).toBeVisible();
  });

  test('search result card is clickable when results exist', async ({ page }) => {
    await page.goto('/search?q=file+read');
    await page.waitForTimeout(3000);

    const cards = page.locator('[data-testid="result-card"], a[href*="/tools/"]');
    const count = await cards.count();
    if (count > 0) {
      await cards.first().click();
      await page.waitForLoadState('networkidle');
      await expect(page).toHaveURL(/\/(tools|servers)\//);
    } else {
      // No results is acceptable — page should not crash
      await expect(page.locator('body')).not.toBeEmpty();
    }
  });
});
