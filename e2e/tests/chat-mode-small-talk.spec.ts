// spec-sha256: 3fbc635f5b8b05bc52e38a96e3d9510782c19b0d3621818c6b4144743a4458f0
// Generated from test_specs/chat-mode-small-talk.md by /e2e. Never hand-edit: run /e2e update chat-mode-small-talk.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/chat-mode-small-talk.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;

test('chat mode small talk', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answers = conversation.getByRole('article', { name: 'Answer', exact: true });
  const progress = conversation.getByRole('list', { name: 'Progress' });

  await page.getByRole('textbox', { name: 'Ask a question' }).fill('Hi');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(answers.first()).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(progress).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  await page.getByRole('textbox', { name: 'Ask a question' }).fill('What is the weather like today?');
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(answers.nth(1)).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(progress).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  // Shape checks from the spec's expected results.
  await expect(answers).toHaveCount(2);
  for (const index of [0, 1]) {
    await expect(answers.nth(index)).not.toBeEmpty();
    await expect(answers.nth(index).getByRole('link')).toHaveCount(0);
  }
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
});
