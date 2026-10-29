// spec-sha256: abb47ee1bf79f9c44dc70288c1980c63620e2cd7a4009af7bd054216a73447d2
// Generated from test_specs/agent-forecaster-answers-in-polish.md by /e2e. Never hand-edit: run /e2e update agent-forecaster-answers-in-polish.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-forecaster-answers-in-polish.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
// The forecast's wall cap is 900 s (the spec's wait); its answer arrives once, at the end.
const FORECAST_TIMEOUT_MS = 900_000;
const STREAM_URL = '/api/run_pipeline/stream';
const METER_LABEL = /^(\d+) of ([1-9]\d*) research turns used today$/;
const FORECAST_COST = 20;

test('a Polish forecast answers in Polish with working links', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  test.setTimeout(FORECAST_TIMEOUT_MS + ANSWER_TIMEOUT_MS + 30_000);
  await page.goto('/chat');
  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answer = conversation.getByRole('article', { name: 'Answer', exact: true });
  const meter = page.getByRole('img', { name: METER_LABEL });
  await expect(meter).toBeVisible();
  const [, used, limit] = (await meter.getAttribute('aria-label'))!.match(METER_LABEL)!;

  await page.getByRole('textbox', { name: 'Ask a question' }).fill('Zrób prognozę: czy NATO przyjmie nowego członka do 2028 roku?');
  const stream = page.waitForResponse((response) => response.url().includes(STREAM_URL), { timeout: FORECAST_TIMEOUT_MS });
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(answer).toBeVisible({ timeout: FORECAST_TIMEOUT_MS });
  await expect(conversation.getByRole('list', { name: 'Progress' })).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  // Shape checks from the spec's expected results.
  await expect(answer).not.toBeEmpty();
  await expect(answer.getByRole('heading', { name: 'Jak głosowała rada' })).toBeVisible();
  await expect(answer.getByRole('heading', { name: /^Twierdzenie \d+/ }).first()).toBeVisible();
  for (const english of ['How the council voted', 'Council verdict', 'voted for']) {
    await expect(answer).not.toContainText(english);
  }
  const hrefs = await answer.getByRole('link').evaluateAll((links) => links.map((link) => link.getAttribute('href') ?? ''));
  expect(hrefs.length).toBeGreaterThan(0);
  for (const href of hrefs) expect(href).toMatch(/^https:\/\//);
  await expect(answer).not.toContainText('source:');
  await expect(answer.getByRole('link', { name: /^Źródło \d+$/ }).first()).toBeVisible();
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
  await expect(meter).toHaveAttribute('aria-label', `${Number(used) + FORECAST_COST} of ${limit} research turns used today`);
  expect(await (await stream).text()).toContain('Council voting, round 1 of 2...');
});
