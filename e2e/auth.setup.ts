import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { test as setup, expect } from '@playwright/test';

const STATE_PATH = `${__dirname}/.auth/user.json`;

setup('log in as the E2E user', async ({ page }) => {
  await page.goto('/accounts/login/');
  await page.getByRole('textbox', { name: 'Email:' }).fill(process.env.E2E_EMAIL!);
  // Not .fill(): Playwright writes filled values into step titles and traces.
  await page
    .getByRole('textbox', { name: 'Password:' })
    .evaluate((el: HTMLInputElement, value) => { el.value = value; }, process.env.E2E_PASSWORD!);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/chat/);
  // Cookies only: the SPA stores a thread id in localStorage on load, and a
  // saved one would put every test into the same conversation.
  const state = await page.context().storageState();
  mkdirSync(dirname(STATE_PATH), { recursive: true });
  writeFileSync(STATE_PATH, JSON.stringify({ ...state, origins: [] }));
});
