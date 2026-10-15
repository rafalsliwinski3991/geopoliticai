// spec-sha256: 968040c4f1125569e5a003dfc171cb2ca25dcd71c5a1985a21f053e877f70bf3
// Generated from test_specs/deep-dive-answers.md by /e2e. Never hand-edit: run /e2e update deep-dive-answers.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/deep-dive-answers.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;

test('deep dive answers', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  await page
    .getByRole('textbox', { name: 'Ask a question' })
    .fill("Give me a deep dive on the history of NATO's Article 5.");
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
