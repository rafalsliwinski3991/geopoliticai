import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { test as setup } from '@playwright/test';
import { signIn } from './users';

const STATE_PATH = `${__dirname}/.auth/user.json`;

setup('log in as the E2E user', async ({ page }) => {
  const { E2E_EMAIL: email, E2E_PASSWORD: password } = process.env;
  if (!email || !password) throw new Error('Set E2E_EMAIL and E2E_PASSWORD in the root .env first.');
  await signIn(page, email, password);
  // Cookies only: the SPA stores a thread id in localStorage on load, and a
  // saved one would put every test into the same conversation.
  const state = await page.context().storageState();
  mkdirSync(dirname(STATE_PATH), { recursive: true });
  writeFileSync(STATE_PATH, JSON.stringify({ ...state, origins: [] }));
});
