// spec-sha256: aa9a2fef5aaea1064a27b0025dfff4ef80326f57836e08a9e7888dd58849e851
// Generated from test_specs/auth-logout-requires-login.md by /e2e. Never hand-edit: run /e2e update auth-logout-requires-login.
import { test, expect } from '../fixtures';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/auth-logout-requires-login.md`, 'utf8');

// Own session: logging out ends the server session, which the shared saved login would lose.
// No trace or screenshot: a trace of the login records the password.
test.use({ storageState: { cookies: [], origins: [] }, trace: 'off', screenshot: 'off' });

test('logout requires login', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/accounts/login/');
  await page.getByRole('textbox', { name: 'Email:' }).fill(process.env.E2E_EMAIL!);
  // Not .fill(): Playwright writes filled values into step titles and traces.
  await page
    .getByRole('textbox', { name: 'Password:' })
    .evaluate((el: HTMLInputElement, value) => { el.value = value; }, process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/chat/);

  await page.goto('/accounts/logout/');
  await page.getByRole('button', { name: /sign out/i }).click();
  await expect(page).toHaveURL(/localhost:8082\/$/);
  await expect(page.getByRole('link', { name: 'Sign in' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Sign out' })).toHaveCount(0);

  await page.goto('/chat');
  await expect(page).toHaveURL(/\/accounts\/login\//);
});
