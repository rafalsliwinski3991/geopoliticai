// spec-sha256: 491903ae7ab20a49340f08e478c3860a5a3a4d15f6e09300ea194090dbdbeef3
// Generated from test_specs/agent-chat-small-talk.md by /e2e. Never hand-edit: run /e2e update agent-chat-small-talk.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-chat-small-talk.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const STREAM_URL = '/api/run_pipeline/stream';

test('chat mode small talk', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  test.setTimeout(4 * ANSWER_TIMEOUT_MS + 30_000);
  await page.goto('/chat');
  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answers = conversation.getByRole('article', { name: 'Answer', exact: true });
  const progress = conversation.getByRole('list', { name: 'Progress' });
  const meter = page.getByRole('img', { name: /^\d+ of [1-9]\d* research turns used today$/ });
  await expect(meter).toBeVisible();
  const meterBefore = await meter.getAttribute('aria-label');

  await page.getByRole('textbox', { name: 'Ask a question' }).fill('Hi');
  const firstStream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(answers.first()).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(progress).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  await page.getByRole('textbox', { name: 'Ask a question' }).fill('What is the weather like today?');
  const secondStream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
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
  await expect(meter).toHaveAttribute('aria-label', meterBefore!);
  for (const stream of [firstStream, secondStream]) {
    expect(await (await stream).text()).not.toContain('Searching and reading sources...');
  }
});
