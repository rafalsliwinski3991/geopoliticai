// spec-sha256: 088c829cd16b38d8f34a7a0038c9ec7f12badc714769ae01a1611ae69d637939
// Generated from test_specs/chat-opens-without-errors.md by /e2e. Never hand-edit: run /e2e update chat-opens-without-errors.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/chat-opens-without-errors.md`, 'utf8');

test('chat opens without errors', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  const consoleErrors: string[] = [];
  const failedApiRequests: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('response', (response) => {
    if (response.url().includes('/api/') && response.status() >= 400) {
      failedApiRequests.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto('/chat');
  // The meter and the conversation list render from /api responses: once both show, the page has settled.
  const sidebar = page.getByRole('navigation', { name: 'Conversations', exact: true });
  await expect(page.getByRole('img', { name: /^\d+ of \d+ research turns used today$/ })).toBeVisible();
  await expect(sidebar).toBeVisible();

  await expect(page.getByRole('textbox', { name: 'Ask a question' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeVisible();
  await expect(page.getByText('Research turns today')).toBeVisible();
  await expect(
    page.getByRole('region', { name: 'Conversation' }).locator('.who', { hasText: /^Error$/ }),
  ).toHaveCount(0);
  expect(consoleErrors).toEqual([]);
  expect(failedApiRequests).toEqual([]);
});
