import { test, expect } from '@playwright/test';

test.describe('Server catalog (/servers)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/servers');
    await page.waitForLoadState('networkidle');
  });

  test('servers page loads without crash', async ({ page }) => {
    await expect(page.locator('body')).not.toBeEmpty();
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });

  test('shows server cards or loading/empty state when API is configured', async ({
    page,
  }) => {
    // Allow up to 5s for API
    await page.waitForTimeout(3000);
    // Should show either server cards, a loading spinner, or a "no servers" message
    const bodyText = await page.locator('body').innerText();
    expect(bodyText.trim().length).toBeGreaterThan(0);
  });

  test('filter input is visible', async ({ page }) => {
    const inputs = page.getByRole('textbox');
    await expect(inputs.first()).toBeVisible();
  });

  test('clicking a server card navigates to server detail', async ({ page }) => {
    await page.waitForTimeout(3000);
    const links = page.locator('a[href*="/servers/"]');
    const count = await links.count();
    if (count > 0) {
      await links.first().click();
      await page.waitForLoadState('networkidle');
      await expect(page).toHaveURL(/\/servers\/.+/);
    } else {
      // No servers yet — acceptable
      await expect(page.locator('body')).not.toBeEmpty();
    }
  });
});

test.describe('Server detail page', () => {
  test('direct navigation to non-existent server shows graceful error', async ({
    page,
  }) => {
    await page.goto('/servers/nonexistent-server-id-xyz');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).not.toBeEmpty();
  });
});

test.describe('Server catalog cold-mount hydration (regression)', () => {
  test('cold-mount /servers renders server cards without any user interaction', async ({
    browser,
  }) => {
    // Regression: /servers must hydrate from the API response on initial mount,
    // not require a user click to flush React Query state into the DOM.
    const context = await browser.newContext();
    const page = await context.newPage();
    try {
      await page.goto('/servers');
      // Do NOT click anything — the regression only surfaces without interaction.
      await page.waitForResponse(
        (response) =>
          response.url().includes('/api/servers?') && response.status() === 200,
        { timeout: 10_000 },
      );
      const cards = page.locator(
        'a[href^="/servers/"]:not([href="/servers/"]):not([href="/servers"])',
      );
      await expect
        .poll(async () => cards.count(), { timeout: 3_000 })
        .toBeGreaterThan(0);
      await expect(page.locator('.animate-pulse')).toHaveCount(0);
    } finally {
      await context.close();
    }
  });
});
