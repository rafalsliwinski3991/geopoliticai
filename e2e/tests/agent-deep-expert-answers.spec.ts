// spec-sha256: a30e13fbcb335ce84d34751f32cccab59c39861f8f448a47ea7b5d25cd0970f7
// Generated from test_specs/agent-deep-expert-answers.md by /e2e. Never hand-edit: run /e2e update agent-deep-expert-answers.
import { test, expect, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-deep-expert-answers.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const DEEP_ANSWER_TIMEOUT_MS = 500_000;
const DEEP_TURN_COST = 10;

async function turnsUsed(page: Page): Promise<number> {
  const meter = page.getByRole('img', { name: /^\d+ of \d+ research turns used today$/ });
  await expect(meter).toBeVisible();
  return Number((await meter.getAttribute('aria-label'))!.split(' ')[0]);
}

test('deep dive answers', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  test.setTimeout(DEEP_ANSWER_TIMEOUT_MS + ANSWER_TIMEOUT_MS + 30_000);
  await page.goto('/chat');
  const usedBefore = await turnsUsed(page);
  await page
    .getByRole('textbox', { name: 'Ask a question' })
    .fill("Give me a deep dive on the history of NATO's Article 5.");
  await page.getByRole('button', { name: 'Send' }).click();

  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answer = conversation.getByRole('article', { name: 'Answer', exact: true });
  await expect(answer).toBeVisible({ timeout: DEEP_ANSWER_TIMEOUT_MS });
  await expect(conversation.getByRole('list', { name: 'Progress' })).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  // Shape checks from the spec's expected results.
  await expect(answer).not.toBeEmpty();
  await expect(answer.getByRole('link').first()).toBeVisible();
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
  await expect(page.getByRole('img', { name: new RegExp(`^${usedBefore + DEEP_TURN_COST} of \\d+ research turns used today$`) })).toBeVisible();
});
