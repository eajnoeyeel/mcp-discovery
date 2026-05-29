import { test, expect } from '@playwright/test';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ARTIFACTS_DIR = path.resolve(__dirname, '../playwright-artifacts');

test.beforeAll(() => {
  fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
});

test.describe('Visual snapshots (non-regression screenshots)', () => {
  test('landing page full screenshot', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.screenshot({
      path: path.join(ARTIFACTS_DIR, 'landing.png'),
      fullPage: true,
    });
    // Title is set by index.html — accept whatever value is set (not empty)
    const title = await page.title();
    expect(title.length).toBeGreaterThan(0);
  });

  test('search page screenshot (empty)', async ({ page }) => {
    await page.goto('/search');
    await page.waitForLoadState('networkidle');
    await page.screenshot({
      path: path.join(ARTIFACTS_DIR, 'search-empty.png'),
      fullPage: true,
    });
  });

  test('search page screenshot (with results)', async ({ page }) => {
    await page.goto('/search?q=github');
    await page.waitForTimeout(3000);
    await page.screenshot({
      path: path.join(ARTIFACTS_DIR, 'search-results.png'),
      fullPage: true,
    });
  });

  test('servers catalog screenshot', async ({ page }) => {
    await page.goto('/servers');
    await page.waitForTimeout(3000);
    await page.screenshot({
      path: path.join(ARTIFACTS_DIR, 'servers.png'),
      fullPage: true,
    });
  });

  test('login page screenshot', async ({ page }) => {
    await page.goto('/login');
    await page.waitForLoadState('networkidle');
    await page.screenshot({
      path: path.join(ARTIFACTS_DIR, 'login.png'),
      fullPage: true,
    });
  });
});
