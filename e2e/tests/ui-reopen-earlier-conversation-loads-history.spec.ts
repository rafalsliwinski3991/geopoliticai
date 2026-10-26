// spec-sha256: dec161e396bc73dc5abd83df6bc89bfa60b826178aec729b96c31613bba70302
// Generated from test_specs/ui-reopen-earlier-conversation-loads-history.md by /e2e. Never hand-edit: run /e2e update ui-reopen-earlier-conversation-loads-history.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/ui-reopen-earlier-conversation-loads-history.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const QUESTION = "What is NATO's Article 5?";

test('reopening an earlier conversation loads its history', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  await expect(page.getByRole('img', { name: /^\d+ of [1-9]\d* research turns used today$/ })).toBeVisible();
  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answer = conversation.getByRole('article', { name: 'Answer', exact: true });
  const progress = conversation.getByRole('list', { name: 'Progress' });

  await page.getByRole('textbox', { name: 'Ask a question' }).fill(QUESTION);
  await page.getByRole('button', { name: 'Send' }).click();
  await expect(answer).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(progress).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  await page.getByRole('button', { name: 'New conversation' }).click();
  await expect(page.getByRole('heading', { name: 'New conversation', level: 1 })).toBeVisible();
  await expect(answer).toHaveCount(0);

  // The newest conversation is listed first, so .first() is the one just asked.
  const sidebar = page.getByRole('navigation', { name: 'Conversations', exact: true });
  await sidebar.getByRole('link', { name: new RegExp(`^${QUESTION.replace('?', '\\?')}`) }).first().click();

  // Shape checks from the spec's expected results.
  await expect(page.getByRole('heading', { name: QUESTION, level: 1 })).toBeVisible();
  await expect(conversation.getByText(QUESTION, { exact: true })).toBeVisible();
  await expect(answer).toBeVisible();
  await expect(answer).not.toBeEmpty();
  await expect(answer.getByRole('link').first()).toBeVisible();
  await expect(progress).toHaveCount(0);
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);

  await page.reload();
  await expect(page.getByRole('heading', { name: QUESTION, level: 1 })).toBeVisible();
  await expect(conversation.getByText(QUESTION, { exact: true })).toBeVisible();
  await expect(answer).toBeVisible();
  await expect(answer).not.toBeEmpty();
});
