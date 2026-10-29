// spec-sha256: 16a0ac8980393bfaf6c8f69d0c0348adeee22b6923eb7d6c8e51f58701e1be16
// Generated from test_specs/agent-other-language-is-refused-in-english.md by /e2e. Never hand-edit: run /e2e update agent-other-language-is-refused-in-english.
import { test, expect } from '../fixtures';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-other-language-is-refused-in-english.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const STREAM_URL = '/api/run_pipeline/stream';
const METER_LABEL = /^(\d+) of ([1-9]\d*) research turns used today$/;
const POLISH_LETTER = /[ąćęłńóśźż]/i;

test('a message in another language is refused in English at no cost', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
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

  const stream = await ask('¿Qué es el Artículo 5 de la OTAN?', 0);

  // Shape checks from the spec's expected results.
  const answer = answers.first();
  await expect(answer).not.toBeEmpty();
  await expect(answer.getByRole('link')).toHaveCount(0);
  await expect(answer).toContainText('Polish');
  await expect(answer).not.toContainText('What next?');
  expect(await (await stream).text()).not.toContain('Searching and reading sources...');
  await expect(meter).toHaveAttribute('aria-label', usedLabel(Number(used)));
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
});
