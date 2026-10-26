// spec-sha256: 1ceb5c63d69692a417b261e45818240b87ebb6934c4570f53bfb0933e33861b8
// Generated from test_specs/ui-composer-blocks-empty-send.md by /e2e. Never hand-edit: run /e2e update ui-composer-blocks-empty-send.
import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/ui-composer-blocks-empty-send.md`, 'utf8');
const METER = /^\d+ of [1-9]\d* research turns used today$/;

test('the question box ignores an empty message', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  const meter = page.getByRole('img', { name: METER });
  await expect(meter).toBeVisible();
  const usedBefore = await meter.getAttribute('aria-label');

  await page.getByRole('button', { name: 'Send' }).click();
  await page.getByRole('textbox', { name: 'Ask a question' }).fill('   ');
  await page.getByRole('button', { name: 'Send' }).click();

  // Shape checks from the spec's expected results.
  const conversation = page.getByRole('region', { name: 'Conversation' });
  await expect(conversation.getByRole('article')).toHaveCount(0);
  await expect(conversation.getByRole('list', { name: 'Progress' })).toHaveCount(0);
  await expect(page.getByRole('img', { name: METER })).toHaveAttribute('aria-label', usedBefore!);
  await expect(conversation.locator('.who', { hasText: /^Error$/ })).toHaveCount(0);
});
