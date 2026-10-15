// spec-sha256: 852c759bb6d14a9d4ee06a0213c2507caac15f25b3dc6e65b27eab7f8f7dddb7
// Generated from test_specs/ask-shows-source.md by /e2e. Never hand-edit: run /e2e update ask-shows-source.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/ask-shows-source.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;

test('ask a question and see a source', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  await page.getByRole('textbox', { name: 'Ask a question' }).fill("What is NATO's Article 5?");
  await page.getByRole('button', { name: 'Send' }).click();

  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answer = conversation.getByRole('article', { name: 'Answer', exact: true });
  await expect(answer).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(conversation.getByRole('list', { name: 'Progress' })).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  // Shape checks from the spec's expected results.
  await expect(answer).not.toBeEmpty();
  await expect(answer.getByRole('link').first()).toBeVisible();
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
});
