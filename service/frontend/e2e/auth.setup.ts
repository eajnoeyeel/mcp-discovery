/**
 * Auth setup — 직접 브라우저에서 Google OAuth 로그인 후 세션 저장.
 *
 * 실행:
 *   npx playwright test --project=setup
 *
 * 브라우저가 뜨면 직접 로그인 → 대시보드(/dashboard)가 열릴 때까지 기다렸다가
 * Inspector의 Resume 버튼(▶)을 누르면 auth 상태가 저장됩니다.
 */
import { test as setup, expect } from '@playwright/test';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const AUTH_FILE = path.join(__dirname, '../playwright/.auth/user.json');

setup('Google OAuth 로그인 → auth 상태 저장', async ({ page }) => {
  await page.goto('/login');
  await page.waitForLoadState('networkidle');

  // 로그인 버튼이 보이는지 확인
  await expect(page.locator('body')).not.toBeEmpty();

  console.log('\n========================================');
  console.log('브라우저에서 Google 로그인을 완료하세요.');
  console.log('/dashboard 페이지가 열리면 Resume(▶)을 누르세요.');
  console.log('========================================\n');

  // Inspector 중단 — 직접 로그인 후 Resume
  await page.pause();

  // 로그인 후 /dashboard에 있는지 확인
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 60_000 });

  // auth 상태(쿠키 + localStorage) 저장
  await page.context().storageState({ path: AUTH_FILE });
  console.log(`\nAuth 상태 저장 완료: ${AUTH_FILE}`);
});
