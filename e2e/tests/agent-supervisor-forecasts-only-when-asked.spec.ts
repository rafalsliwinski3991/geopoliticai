// spec-sha256: 93089104ba6ea8c4a66abbfe343f81fd48d3f8b4aa15d3ac15c4b9c50e6e0b58
// Generated from test_specs/agent-supervisor-forecasts-only-when-asked.md by /e2e. Never hand-edit: run /e2e update agent-supervisor-forecasts-only-when-asked.
import { test, expect } from '../fixtures';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-supervisor-forecasts-only-when-asked.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const STREAM_URL = '/api/run_pipeline/stream';
const METER_LABEL = /^(\d+) of ([1-9]\d*) research turns used today$/;

test('a forward-looking question does not start a forecast', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answer = conversation.getByRole('article', { name: 'Answer', exact: true });
  const meter = page.getByRole('img', { name: METER_LABEL });
  await expect(meter).toBeVisible();
  const [, used, limit] = (await meter.getAttribute('aria-label'))!.match(METER_LABEL)!;

  await page.getByRole('textbox', { name: 'Ask a question' }).fill('Which countries are in talks to join NATO, and how far along are they?');
  const stream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(answer).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(conversation.getByRole('list', { name: 'Progress' })).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  // Shape checks from the spec's expected results.
  await expect(answer).not.toBeEmpty();
  await expect(answer.getByRole('link').first()).toBeVisible();
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
  await expect(answer).not.toContainText('How the council voted');
  expect(await (await stream).text()).not.toContain('Council voting, round 1 of 2...');
  await expect(meter).toHaveAttribute('aria-label', `${Number(used) + 1} of ${limit} research turns used today`);
});
