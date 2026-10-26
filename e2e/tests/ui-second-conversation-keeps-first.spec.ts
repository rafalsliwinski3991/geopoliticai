// spec-sha256: 32f7f3b8c71d759f1fb9a226cbd92e541b6d00423b1ece59196a2e7b8cf3b42e
// Generated from test_specs/ui-second-conversation-keeps-first.md by /e2e. Never hand-edit: run /e2e update ui-second-conversation-keeps-first.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/ui-second-conversation-keeps-first.md`, 'utf8');
const ANSWER_TIMEOUT_MS = 150_000;
const QUESTION = "What is NATO's Article 5?";

test('second conversation keeps the first', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  const sidebar = page.getByRole('navigation', { name: 'Conversations', exact: true });
  // The meter and the conversation list settle together, when the meter's limit turns non-zero:
  // it reads "0 of 0" while loading, so a count taken then would be 0.
  await expect(page.getByRole('img', { name: /^\d+ of [1-9]\d* research turns used today$/ })).toBeVisible();
  // Earlier runs leave identical titles behind, so count them instead of looking for one.
  const firstConversations = sidebar.getByRole('link', { name: /^What is NATO's Article 5\?/ });
  const listedBefore = await firstConversations.count();

  await page.getByRole('textbox', { name: 'Ask a question' }).fill(QUESTION);
  await page.getByRole('button', { name: 'Send' }).click();
  const conversation = page.getByRole('region', { name: 'Conversation' });
  const answer = conversation.getByRole('article', { name: 'Answer', exact: true });
  await expect(answer).toBeVisible({ timeout: ANSWER_TIMEOUT_MS });
  await expect(conversation.getByRole('list', { name: 'Progress' })).toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS });

  await page.getByRole('button', { name: 'New conversation' }).click();
  await expect(page.getByRole('heading', { name: 'New conversation', level: 1 })).toBeVisible();
  await page.reload();

  // Shape checks from the spec's expected results.
  await expect(page.getByRole('heading', { name: 'New conversation', level: 1 })).toBeVisible();
  await expect(conversation.getByRole('article')).toHaveCount(0);
  await expect(firstConversations).toHaveCount(listedBefore + 1);
  await firstConversations.first().click();
  await expect(page.getByRole('heading', { name: QUESTION, level: 1 })).toBeVisible();
  await expect(answer).toBeVisible();
  await expect(answer).not.toBeEmpty();
});
