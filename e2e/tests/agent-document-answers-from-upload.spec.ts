// spec-sha256: 5c101dadc6ae4c0f4283aa1ee20ef2672a04853a4d7a25ff657a37e2aa226ff9
// Generated from test_specs/agent-document-answers-from-upload.md by /e2e. Never hand-edit: run /e2e update agent-document-answers-from-upload.
import { test, expect } from '../fixtures';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/agent-document-answers-from-upload.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const CHIP = '.document-chip'; // the sidebar also lists a thread titled with the file name
const FILE_NAME = 'harbor-notes.txt';
const FILE_TEXT = 'The Kestrel Harbor ferry timetable changed to 7 departures a day in 2031.';
const DOCUMENT_FOOTER = 'Answers come from your document while one is attached.';

test('answer a question from an uploaded document', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: 'Attach' }).click();
  await (await chooser).setFiles({ name: FILE_NAME, mimeType: 'text/plain', buffer: Buffer.from(FILE_TEXT) });

  // After step 3 the chip shows the file name and the footer names the document.
  await expect(page.locator(CHIP)).toContainText(FILE_NAME, { timeout: ANSWER_TIMEOUT_MS });
  await expect(page.getByText(DOCUMENT_FOOTER)).toBeVisible();

  await page.getByRole('textbox', { name: 'Ask a question' }).fill('How many departures a day does the Kestrel Harbor ferry have?');
  await page.getByRole('button', { name: 'Send' }).click();

  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answer = conversation.getByRole('article', { name: 'Answer', exact: true });
  await expect(answer).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(conversation.getByRole('list', { name: 'Progress' })).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  // Shape checks from the spec's expected results.
  await expect(answer).toContainText('7');
  await expect(answer).toContainText('[excerpt 1]');
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);

  // Step 5: remove the document so the test user keeps no file behind.
  await page.getByRole('button', { name: 'Remove document' }).click();
  await expect(page.locator(CHIP)).toHaveCount(0);
  await expect(page.getByText(DOCUMENT_FOOTER)).toHaveCount(0);
});
