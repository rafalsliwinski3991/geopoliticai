import { expect, type Page } from '@playwright/test';

// One test user per worker, so parallel tests never share a research meter or a
// sidebar. Keep it equal to `E2E_USER_COUNT` in web_backend/users/services.py.
export const E2E_WORKERS = 4;

// Worker 0 is E2E_EMAIL itself; worker n is its `+<n + 1>` sibling (`e2e+2@x`), the
// addresses `make e2e-user` creates.
export function workerEmail(email: string, workerIndex: number): string {
  if (workerIndex === 0) return email;
  const [local, domain] = [email.slice(0, email.lastIndexOf('@')), email.slice(email.lastIndexOf('@') + 1)];
  return `${local}+${workerIndex + 1}@${domain}`;
}

export async function signIn(page: Page, email: string, password: string): Promise<void> {
  await page.goto('/accounts/login/');
  await page.getByRole('textbox', { name: 'Email:' }).fill(email);
  // Not .fill(): Playwright writes filled values into step titles and traces.
  await page
    .getByRole('textbox', { name: 'Password:' })
    .evaluate((el: HTMLInputElement, value) => { el.value = value; }, password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/chat/);
}
