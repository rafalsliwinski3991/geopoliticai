// spec-sha256: 2ed7ed748d4e220430d72ce0769d5c598d4a2f534f75e8c1c283f68c677dd954
// Generated from test_specs/public-pages-load.md by /e2e. Never hand-edit: run /e2e update public-pages-load.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/public-pages-load.md`, 'utf8');
const HTML_PAGES = ['/', '/about/', '/privacy/', '/accounts/login/'];
const TEXT_PAGES = ['/robots.txt', '/sitemap.xml', '/llms.txt'];

test.use({ storageState: { cookies: [], origins: [] } });

test('public pages load', { annotation: { type: 'spec', description: SPEC } }, async ({ page, request }) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(`${page.url()}: ${message.text()}`);
  });
  page.on('response', (response) => {
    if (response.status() >= 400) failedRequests.push(`${response.status()} ${response.url()}`);
  });

  for (const path of HTML_PAGES) {
    const response = await page.goto(path);
    expect(response?.status(), path).toBe(200);
    await expect(page.getByRole('heading').first(), path).toBeVisible();
  }
  for (const path of TEXT_PAGES) {
    const response = await page.goto(path);
    expect(response?.status(), path).toBe(200);
    expect((await response!.text()).trim().length, path).toBeGreaterThan(0);
  }

  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);

  const health = await request.get('/api/health');
  expect(health.status()).toBe(200);
});
