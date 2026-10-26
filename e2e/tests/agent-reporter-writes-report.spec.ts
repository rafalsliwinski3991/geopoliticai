// spec-sha256: 7c35fc217252d19a44308f89b82a614a5f06c68d83ab2ca50f7c46a92355a2e4
// Generated from test_specs/agent-reporter-writes-report.md by /e2e. Never hand-edit: run /e2e update agent-reporter-writes-report.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-reporter-writes-report.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const STREAM_URL = '/api/run_pipeline/stream';

test('the report agent outlines and writes a report', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  test.setTimeout(5 * ANSWER_TIMEOUT_MS + 30_000);
  await page.goto('/chat');
  await expect(page.getByRole('img', { name: /^\d+ of [1-9]\d* research turns used today$/ })).toBeVisible();
  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answers = conversation.getByRole('article', { name: 'Answer', exact: true });
  const progress = conversation.getByRole('list', { name: 'Progress' });
  const box = page.getByRole('textbox', { name: 'Ask a question' });
  const send = page.getByRole('button', { name: 'Send' });

  await box.fill("What is NATO's Article 5?");
  await send.click();
  await expect(answers).toHaveCount(1, { timeout: ANSWER_TIMEOUT_MS });
  await expect(progress).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  await box.fill('Write me a report on what we have covered.');
  const outlineStream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
  await send.click();
  const outline = conversation.getByText('Here is the outline I would write.');
  await expect(outline).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(conversation.locator('.gate li').first()).toBeVisible();

  await box.fill('approve');
  const reportStream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
  await send.click();
  await expect(answers).toHaveCount(2, { timeout: ANSWER_TIMEOUT_MS });
  await expect(progress).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  // Shape checks from the spec's expected results.
  expect(await (await outlineStream).text()).toContain('Reading the conversation...');
  expect(await (await reportStream).text()).toContain('Writing the report...');
  await expect(answers.last()).not.toBeEmpty();
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
});
