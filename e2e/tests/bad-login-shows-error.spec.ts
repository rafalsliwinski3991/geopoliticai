// spec-sha256: c3484a973255fb5a8b4df82683405772cfea92dce441993d5be627fc6166ac15
// Generated from test_specs/bad-login-shows-error.md by /e2e. Never hand-edit: run /e2e update bad-login-shows-error.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/bad-login-shows-error.md`, 'utf8');

test.use({ storageState: { cookies: [], origins: [] } });

test('bad login shows an error', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/accounts/login/');
  await page.getByRole('textbox', { name: 'Email:' }).fill('nobody@example.com');
  await page.getByRole('textbox', { name: 'Password:' }).fill('wrong-password-123');
  await page.getByRole('button', { name: 'Sign in' }).click();

  await expect(page).toHaveURL(/\/accounts\/login\//);
  await expect(page.getByRole('heading', { name: 'Sign in', level: 1 })).toBeVisible();
  await expect(
    page.getByText('The email address and/or password you specified are not correct.'),
  ).toBeVisible();
  await expect(page).not.toHaveURL(/\/chat/);
});
