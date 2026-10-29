// spec-sha256: 6345ffdb70e0961d9d91c3743a37f2913174432c3fe2c8f825555cc15d628a2f
// Generated from test_specs/agent-mixed-language-message-is-not-refused.md by /e2e. Never hand-edit: run /e2e update agent-mixed-language-message-is-not-refused.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-mixed-language-message-is-not-refused.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const STREAM_URL = '/api/run_pipeline/stream';
const METER_LABEL = /^(\d+) of ([1-9]\d*) research turns used today$/;
const POLISH_LETTER = /[ąćęłńóśźż]/i;

test('a Polish message with an English phrase is answered, not refused', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answers = conversation.getByRole('article', { name: 'Answer', exact: true });
  const progress = conversation.getByRole('list', { name: 'Progress' });
  const meter = page.getByRole('img', { name: METER_LABEL });
  await expect(meter).toBeVisible();
  const [, used, limit] = (await meter.getAttribute('aria-label'))!.match(METER_LABEL)!;
  const usedLabel = (turns: number) => `${turns} of ${limit} research turns used today`;

  async function ask(question: string, index: number) {
    await page.getByRole('textbox', { name: 'Ask a question' }).fill(question);
    const stream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
    await page.getByRole('button', { name: 'Send' }).click();
    await expect(answers.nth(index)).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
    await expect(progress).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });
    return stream;
  }

  const stream = await ask('Czy NATO zwiększy wydatki na obronę po latest summit?', 0);

  // Shape checks from the spec's expected results.
  const answer = answers.first();
  await expect(answer).not.toBeEmpty();
  await expect(answer.getByRole('link').first()).toBeVisible();
  await expect(answer).not.toContainText('supports only English and Polish');
  expect(await (await stream).text()).toContain('Searching and reading sources...');
  await expect(meter).toHaveAttribute('aria-label', usedLabel(Number(used) + 1));
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
});
