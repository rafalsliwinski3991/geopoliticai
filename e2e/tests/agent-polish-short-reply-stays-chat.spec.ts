// spec-sha256: 127f8f3b22c3fb154e0472b9c147008228188fdd450979a7c4fcce2378e03acc
// Generated from test_specs/agent-polish-short-reply-stays-chat.md by /e2e. Never hand-edit: run /e2e update agent-polish-short-reply-stays-chat.
import { test, expect } from '../fixtures';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-polish-short-reply-stays-chat.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const STREAM_URL = '/api/run_pipeline/stream';
const METER_LABEL = /^(\d+) of ([1-9]\d*) research turns used today$/;
const POLISH_LETTER = /[ąćęłńóśźż]/i;

test('a short Polish reply stays a free Polish chat turn', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  test.setTimeout(4 * ANSWER_TIMEOUT_MS + 30_000);
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

  const firstStream = await ask('Cześć', 0);
  const secondStream = await ask('Dziękuję', 1);

  // Shape checks from the spec's expected results.
  await expect(answers).toHaveCount(2);
  for (const index of [0, 1]) {
    await expect(answers.nth(index)).not.toBeEmpty();
    await expect(answers.nth(index).getByRole('link')).toHaveCount(0);
    await expect(answers.nth(index)).not.toContainText('What next?');
  }
  await expect(answers.nth(1)).toContainText(POLISH_LETTER);
  for (const stream of [firstStream, secondStream]) {
    expect(await (await stream).text()).not.toContain('Searching and reading sources...');
  }
  await expect(meter).toHaveAttribute('aria-label', usedLabel(Number(used)));
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
});
