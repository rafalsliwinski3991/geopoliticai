// spec-sha256: db630a25a85fd9933900b0f6c53c85bec056814f0cddd9690eaed86127102c0b
// Generated from test_specs/ui-daily-limit-is-50.md by /e2e. Never hand-edit: run /e2e update ui-daily-limit-is-50.
import { test, expect } from '../fixtures';
import { readFileSync } from 'node:fs';

const SPEC = readFileSync(`${__dirname}/../test_specs/ui-daily-limit-is-50.md`, 'utf8');

test('daily research limit is 50', { annotation: { type: 'spec', description: SPEC } }, async ({ page }) => {
  await page.goto('/chat');
  await expect(page.getByText('Research turns today')).toBeVisible();

  // Shape checks from the spec's expected results.
  await expect(page.getByText(/^\d+ of 50$/)).toBeVisible();
  await expect(page.getByRole('img', { name: /^\d+ of 50 research turns used today$/ })).toBeVisible();
  await expect(
    page.getByRole('region', { name: 'Conversation' }).locator('.who', { hasText: /^Error$/ }),
  ).toHaveCount(0);
});
