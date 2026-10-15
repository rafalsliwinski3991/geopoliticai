import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { test as setup, expect } from '@playwright/test';

const STATE_PATH = `${__dirname}/.auth/user.json`;

setup('log in as the E2E user', async ({ page }) => {
  const { E2E_EMAIL: email, E2E_PASSWORD: password } = process.env;
  if (!email || !password) throw new Error('Set E2E_EMAIL and E2E_PASSWORD in the root .env first.');
  await page.goto('/accounts/login/');
  await page.getByRole('textbox', { name: 'Email:' }).fill(email);
  // Not .fill(): Playwright writes filled values into step titles and traces.
  await page
    .getByRole('textbox', { name: 'Password:' })
    .evaluate((el: HTMLInputElement, value) => { el.value = value; }, password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/chat/);
  // Cookies only: the SPA stores a thread id in localStorage on load, and a
  // saved one would put every test into the same conversation.
  const state = await page.context().storageState();
  mkdirSync(dirname(STATE_PATH), { recursive: true });
  writeFileSync(STATE_PATH, JSON.stringify({ ...state, origins: [] }));
});
