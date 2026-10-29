import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { defineConfig } from '@playwright/test';
import { E2E_WORKERS } from './users';

// Each generated test starts with this line plus the sha256 of its spec.
const SPEC_HASH_HEADER = '// spec-sha256: ';
// Covers the two 150 s waits a chat test makes (answer shown, then progress gone) plus its actions,
// so a slow turn fails on the locator's own error, not on the test timeout.
const TEST_TIMEOUT_MS = 330_000;
const ROOT_ENV = `${__dirname}/../.env`;

// A plain `npx playwright test` never regenerates; say so when a spec moved on.
function warnOnStaleTests(): void {
  for (const file of readdirSync(`${__dirname}/tests`).filter((name) => name.endsWith('.spec.ts'))) {
    const stem = file.replace(/\.spec\.ts$/, '');
    const spec = `${__dirname}/test_specs/${stem}.md`;
    if (!existsSync(spec)) {
      console.warn(`e2e: tests/${file} has no spec in test_specs/`);
      continue;
    }
    const hash = createHash('sha256').update(readFileSync(spec)).digest('hex');
    const header = readFileSync(`${__dirname}/tests/${file}`, 'utf8').split('\n', 1)[0];
    if (header !== `${SPEC_HASH_HEADER}${hash}`) {
      console.warn(`e2e: tests/${file} is stale; its spec changed. Run /e2e update ${stem}.`);
    }
  }
}

// E2E_EMAIL and E2E_PASSWORD live in the root .env (the user adds them; CI writes a throwaway one).
if (existsSync(ROOT_ENV)) process.loadEnvFile(ROOT_ENV);
// Workers load this file too; warn once, from the main process.
if (!process.env.TEST_WORKER_INDEX) warnOnStaleTests();

export default defineConfig({
  testDir: '.',
  timeout: TEST_TIMEOUT_MS,
  // Each worker runs as its own user (`fixtures.ts`), so tests on different workers never share a
  // meter, a sidebar or a daily quota; the tests of one worker still run one at a time.
  workers: E2E_WORKERS,
  reporter: [['list'], ['html', { open: 'never' }], ['json', { outputFile: 'test-results/results.json' }]],
  use: { baseURL: 'http://localhost:8082', screenshot: 'on', trace: 'on' },
  projects: [
    // No trace or screenshot for the login: a trace records every value the page holds.
    { name: 'setup', testMatch: /auth\.setup\.ts/, use: { trace: 'off', screenshot: 'off' } },
    {
      name: 'e2e',
      testDir: './tests',
      dependencies: ['setup'],
    },
  ],
});
