// spec-sha256: df4afb29a251ea762a11a112d7b1fcd9649010d4220a04b37b2a237d4e3ef228
// Generated from test_specs/agent-expert-answers-with-source.md by /e2e. Never hand-edit: run /e2e update agent-expert-answers-with-source.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-expert-answers-with-source.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const STREAM_URL = '/api/run_pipeline/stream';

test('ask a question and see a source', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  await page.getByRole('textbox', { name: 'Ask a question' }).fill("What is NATO's Article 5?");
  const stream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
  await page.getByRole('button', { name: 'Send' }).click();

  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answer = conversation.getByRole('article', { name: 'Answer', exact: true });
  await expect(answer).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(conversation.getByRole('list', { name: 'Progress' })).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  // Shape checks from the spec's expected results.
  await expect(answer).not.toBeEmpty();
  await expect(answer.getByRole('link').first()).toBeVisible();
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
  expect(await (await stream).text()).toContain('Searching and reading sources...');
});
