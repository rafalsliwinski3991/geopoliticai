// spec-sha256: d5dafd0ad6f0e4ab4a00dccf3e4e647b32fa935f6fb140528fb55f96b523dc97
// Generated from test_specs/agent-polish-chat-and-expert.md by /e2e. Never hand-edit: run /e2e update agent-polish-chat-and-expert.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-polish-chat-and-expert.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const STREAM_URL = '/api/run_pipeline/stream';
const METER_LABEL = /^(\d+) of ([1-9]\d*) research turns used today$/;
const WELCOME_POLISH_NOTE = 'Możesz rozmawiać ze mną po angielsku lub po polsku.';

test('polish welcome, chat greeting, expert answer, and language refusal', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  test.setTimeout(6 * ANSWER_TIMEOUT_MS + 30_000);
  await page.goto('/chat');
  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answers = conversation.getByRole('article', { name: 'Answer', exact: true });
  const progress = conversation.getByRole('list', { name: 'Progress' });
  const welcome = conversation.getByText(WELCOME_POLISH_NOTE);
  const meter = page.getByRole('img', { name: METER_LABEL });
  await expect(meter).toBeVisible();
  const [, used, limit] = (await meter.getAttribute('aria-label'))!.match(METER_LABEL)!;
  const usedLabel = (turns: number) => `${turns} of ${limit} research turns used today`;

  // Before any message: the welcome is visible and no answer exists.
  await expect(welcome).toBeVisible();
  await expect(answers).toHaveCount(0);

  // Step 2: a Polish greeting is free chat.
  await page.getByRole('textbox', { name: 'Ask a question' }).fill('Cześć');
  const greetingStream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(answers.first()).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(progress).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });
  await expect(welcome).toHaveCount(0);
  await expect(answers.first()).not.toBeEmpty();
  await expect(answers.first().getByRole('link')).toHaveCount(0);
  await expect(meter).toHaveAttribute('aria-label', usedLabel(Number(used)));

  // Step 3: a Polish question runs the expert and gets a Polish footer.
  await page.getByRole('textbox', { name: 'Ask a question' }).fill('Czym jest Artykuł 5 NATO?');
  const expertStream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(answers.nth(1)).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(progress).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });
  await expect(answers.nth(1)).not.toBeEmpty();
  await expect(answers.nth(1).getByRole('link').first()).toBeVisible();
  await expect(answers.nth(1)).toContainText(/[ąćęłńóśźż]/i);
  await expect(answers.nth(1)).toContainText('Co dalej?');
  await expect(answers.nth(1)).toContainText('tur');
  await expect(meter).toHaveAttribute('aria-label', usedLabel(Number(used) + 1));
  expect(await (await expertStream).text()).toContain('Searching and reading sources...');

  // Step 4: a German question is refused in chat, for free.
  await page.getByRole('textbox', { name: 'Ask a question' }).fill('Was ist Artikel 5 der NATO?');
  const refusalStream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(answers.nth(2)).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(progress).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });
  await expect(answers).toHaveCount(3);
  await expect(answers.nth(2)).not.toBeEmpty();
  await expect(answers.nth(2).getByRole('link')).toHaveCount(0);
  await expect(answers.nth(2)).toContainText('Polish');
  await expect(meter).toHaveAttribute('aria-label', usedLabel(Number(used) + 1));
  expect(await (await refusalStream).text()).not.toContain('Searching and reading sources...');
  expect(await (await greetingStream).text()).not.toContain('Searching and reading sources...');

  // Step 5: a new conversation brings the welcome back.
  await page.getByRole('button', { name: 'New conversation' }).click();
  await expect(welcome).toBeVisible();
  await expect(answers).toHaveCount(0);

  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
});
