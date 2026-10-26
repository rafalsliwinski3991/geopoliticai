// spec-sha256: acdfc5b94578e316a0f27f044f565a7d11fdd1a4fd451210430e6ee7d4a6b5d0
// Generated from test_specs/ui-new-conversation-starts-empty.md by /e2e. Never hand-edit: run /e2e update ui-new-conversation-starts-empty.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/ui-new-conversation-starts-empty.md`, 'utf8');
const METER = /^\d+ of [1-9]\d* research turns used today$/;

test('a new conversation starts empty', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  const meter = page.getByRole('img', { name: METER });
  await expect(meter).toBeVisible();
  const usedBefore = await meter.getAttribute('aria-label');

  await page.getByRole('button', { name: 'New conversation' }).click();

  // Shape checks from the spec's expected results.
  const conversation = page.getByRole('region', { name: 'Conversation' });
  await expect(page.getByRole('heading', { name: 'New conversation', level: 1 })).toBeVisible();
  await expect(conversation.getByRole('article')).toHaveCount(0);
  await expect(conversation.getByRole('list', { name: 'Progress' })).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: 'Ask a question' })).toBeEmpty();
  await expect(page.getByRole('button', { name: 'Send' })).toBeEnabled();
  await expect(page.getByRole('img', { name: METER })).toHaveAttribute('aria-label', usedBefore!);
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
});
