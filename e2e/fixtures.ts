import { mkdirSync, writeFileSync } from 'node:fs';
import { test as base } from '@playwright/test';
import { signIn, workerEmail } from './users';

// Every test file imports `test` from here: each Playwright worker logs in once as
// its own user (see `users.ts`) and every test it runs starts from that session.
export { expect } from '@playwright/test';

export const test = base.extend<object, { workerStorageState: string }>({
  storageState: ({ workerStorageState }, use) => use(workerStorageState),
  workerStorageState: [
    async ({ browser }, use, workerInfo) => {
      const { E2E_EMAIL: email, E2E_PASSWORD: password } = process.env;
      if (!email || !password) throw new Error('Set E2E_EMAIL and E2E_PASSWORD in the root .env first.');
      const path = `${__dirname}/.auth/worker-${workerInfo.parallelIndex}.json`;
      // A bare context: no trace or screenshot, since a trace records every value the page holds.
      const context = await browser.newContext({ baseURL: workerInfo.project.use.baseURL });
      const page = await context.newPage();
      await signIn(page, workerEmail(email, workerInfo.parallelIndex), password);
      // Cookies only: the SPA stores a thread id in localStorage on load, and a
      // saved one would put every test into the same conversation.
      const state = await context.storageState();
      await context.close();
      mkdirSync(`${__dirname}/.auth`, { recursive: true });
      writeFileSync(path, JSON.stringify({ ...state, origins: [] }));
      await use(path);
    },
    { scope: 'worker' },
  ],
});
