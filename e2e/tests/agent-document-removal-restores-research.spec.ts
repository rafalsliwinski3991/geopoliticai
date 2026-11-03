// spec-sha256: 28972925b64eec567d3dd68662ac363d1a3d6e56b15140437922b3184f29be2a
// Generated from test_specs/agent-document-removal-restores-research.md by /e2e. Never hand-edit: run /e2e update agent-document-removal-restores-research.
import { test, expect } from '../fixtures';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-document-removal-restores-research.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const STREAM_URL = '/api/run_pipeline/stream';
const CHIP = '.document-chip'; // the sidebar also lists a thread titled with the file name
const FILE_NAME = 'harbor-notes.txt';
const FILE_TEXT = 'The Kestrel Harbor ferry timetable changed to 7 departures a day in 2031.';

test('removing a document brings back research answers', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Attach' }).click();
  await (await chooser).setFiles({ name: FILE_NAME, mimeType: 'text/plain', buffer: Buffer.from(FILE_TEXT) });
  await expect(page.locator(CHIP)).toContainText(FILE_NAME, { timeout: ANSWER_TIMEOUT_MS });

  await page.getByRole('button', { name: 'Remove document' }).click();
  await expect(page.locator(CHIP)).toHaveCount(0);

  await page.getByRole('textbox', { name: 'Ask a question' }).fill("What is NATO's Article 5?");
  const stream = page.waitForResponse((response) => response.url().includes(STREAM_URL));
  await page.getByRole('button', { name: 'Send' }).click();

  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answer = conversation.getByRole('article', { name: 'Answer', exact: true });
  await expect(answer).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(conversation.getByRole('list', { name: 'Progress' })).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  // Shape checks from the spec's expected results.
  await expect(answer).not.toBeEmpty();
  await expect(answer.getByRole('link').first()).toBeVisible();
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
  expect(await (await stream).text()).toContain('Searching and reading sources...');
});
