// spec-sha256: 01f71ef550b4c267639d25146fb93edc52cf9c064e040043b556313ef0eb90da
// Generated from test_specs/agent-supervisor-offers-next-steps.md by /e2e. Never hand-edit: run /e2e update agent-supervisor-offers-next-steps.
import { test, expect } from '../fixtures';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-supervisor-offers-next-steps.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const STREAM_URL = '/api/run_pipeline/stream';
const METER_LABEL = /^(\d+) of ([1-9]\d*) research turns used today$/;

test('the supervisor offers next steps after a research answer', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answer = conversation.getByRole('article', { name: 'Answer', exact: true });
  const meter = page.getByRole('img', { name: METER_LABEL });
  await expect(meter).toBeVisible();
  const [, used, limit] = (await meter.getAttribute('aria-label'))!.match(METER_LABEL)!;

  await page.getByRole('textbox', { name: 'Ask a question' }).fill("What is NATO's Article 5?");
  const stream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(answer).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(conversation.getByRole('list', { name: 'Progress' })).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  // Shape checks from the spec's expected results.
  await expect(answer).not.toBeEmpty();
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
  await expect(answer).toContainText('What next?');
  await expect(answer).toContainText('research turn');
  expect(await (await stream).text()).toContain('Searching and reading sources...');
  await expect(meter).toHaveAttribute('aria-label', `${Number(used) + 1} of ${limit} research turns used today`);
});
