// spec-sha256: ca9bf62b4ef9a0fae73d774558f12c125f3eebae4cb013bbd6046f50d57af24a
// Generated from test_specs/agent-supervisor-keeps-follow-up-on-expert.md by /e2e. Never hand-edit: run /e2e update agent-supervisor-keeps-follow-up-on-expert.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-supervisor-keeps-follow-up-on-expert.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const STREAM_URL = '/api/run_pipeline/stream';
const METER_LABEL = /^(\d+) of ([1-9]\d*) research turns used today$/;

test('a plain follow-up stays on the expert', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  test.setTimeout(4 * ANSWER_TIMEOUT_MS + 30_000);
  await page.goto('/chat');
  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answers = conversation.getByRole('article', { name: 'Answer', exact: true });
  const progress = conversation.getByRole('list', { name: 'Progress' });
  const meter = page.getByRole('img', { name: METER_LABEL });
  await expect(meter).toBeVisible();
  const [, used, limit] = (await meter.getAttribute('aria-label'))!.match(METER_LABEL)!;

  await page.getByRole('textbox', { name: 'Ask a question' }).fill("What is NATO's Article 5?");
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(answers.first()).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(progress).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  await page.getByRole('textbox', { name: 'Ask a question' }).fill('Which country was the first to invoke it?');
  const secondStream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(answers.nth(1)).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(progress).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  // Shape checks from the spec's expected results.
  await expect(answers).toHaveCount(2);
  for (const index of [0, 1]) {
    await expect(answers.nth(index)).not.toBeEmpty();
  }
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
  await expect(answers.last().getByRole('link').first()).toBeVisible();
  const secondStreamText = await (await secondStream).text();
  expect(secondStreamText).toContain('Searching and reading sources...');
  expect(secondStreamText).not.toContain('Council voting, round 1 of 2...');
  await expect(meter).toHaveAttribute('aria-label', `${Number(used) + 2} of ${limit} research turns used today`);
});
