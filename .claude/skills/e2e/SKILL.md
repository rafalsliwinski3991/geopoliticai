---
name: e2e
description: >-
  INVOKE THIS SKILL when the user runs /e2e or asks to write, run, or explain an end-to-end (Playwright)
  test of this app: /e2e new "<prompt>", /e2e run [name], /e2e update <name>.
disable-model-invocation: true
---

`/e2e` turns plain-English specs into Playwright tests for the app running under Docker Compose at
`http://localhost:8082`, runs them, and explains the results. Specs in `e2e/test_specs/<name>.md` are the only
files a person edits. Tests in `e2e/tests/<name>.spec.ts` are generated, start with
`// spec-sha256: <sha256 of the spec>`, and change only through Regenerate below.

Rules that hold in every subcommand:

- Never edit a test to make it pass. A failing test gets a verdict, not a fix.
- Write each assertion from the spec's expected results, never from what the page shows now. If the walk
  cannot find what an expected result describes, write the assertion from the spec anyway, say so, and let the
  run fail: that is evidence, not a reason to weaken the check.
- Never read, print, or write the root `.env`, and never type `E2E_PASSWORD` into `playwright-cli`. Login
  belongs to `e2e/auth.setup.ts`; every walk starts from its saved session.
- Run every command from `e2e/` with `npx` (pinned in `e2e/package.json`). If `e2e/node_modules` is missing,
  run `npm ci && npx playwright install chromium` first.
- No AI judging of answer content. Assertions are shape checks: the answer is not empty, it contains at least
  one link, no error bubble is shown, plus what the spec's expected results say about visible structure.
- Every turn spends the test user's daily research units (`DAILY_RESEARCH_TURNS` in
  `agentic_backend/src/config.py`): a chat turn 1, a deep turn `DEEP_RESEARCH_TURN_COST`, a forecast
  `FORECAST_TURN_COST`. Read the numbers there; never restate them.

## Preflight (every subcommand)

1. `curl -fsS -o /dev/null http://localhost:8082/accounts/login/` and
   `curl -fsS -o /dev/null http://localhost:8082/api/health`. If either fails, report
   "Environment problem: the app is not reachable at localhost:8082. Start it with `make up`." and stop.
2. `npx playwright test --project=setup`. If it fails, report "Login failed; no tests ran." with the error
   line, suggest `make e2e-user` (and `docker compose up -d --force-recreate web-backend` after adding
   `E2E_EMAIL`/`E2E_PASSWORD` to `.env`), and stop.

## Regenerate `<name>`

1. Read `test_specs/<name>.md`.
2. Walk it live with a named session, starting logged in:
   - `npx playwright-cli -s=e2e open http://localhost:8082/`
   - `npx playwright-cli -s=e2e state-load .auth/user.json`
   - `npx playwright-cli -s=e2e goto http://localhost:8082/chat`
   - For each step: `npx playwright-cli -s=e2e snapshot`, find the element's ref, then act with
     `fill <ref> "<text>"`, `click <ref>`, `press <key>`, `select <ref> <value>` or `check <ref>`. Copy the
     line each action prints after "Ran Playwright code:".
   - To wait for an answer, repeat `snapshot` until the `list "Progress"` is gone and an `article "Answer"`
     is present, for at most `ANSWER_TIMEOUT_MS` (150 s). Past that, close the session and report that the
     turn did not finish; write no test. Send each question once.
   - `npx playwright-cli -s=e2e close`.
3. Write `tests/<name>.spec.ts`, following `tests/agent-expert-answers-with-source.spec.ts`:
   - line 1: `// spec-sha256: ` + the hash from `sha256sum test_specs/<name>.md`;
   - line 2: `// Generated from test_specs/<name>.md by /e2e. Never hand-edit: run /e2e update <name>.`;
   - read the spec into `SPEC` and pass `{ annotation: { type: 'spec', description: SPEC } }` so the HTML
     report shows it;
   - the copied lines, with `http://localhost:8082` stripped to relative paths (`baseURL` supplies it);
   - waits as `toBeVisible({ timeout: ANSWER_TIMEOUT_MS })` and `toHaveCount(0, { timeout: ANSWER_TIMEOUT_MS })`
     with `ANSWER_TIMEOUT_MS = 150_000`; at most two such waits per turn. A deep turn delivers its answer
     once, at the end, after up to 480 s, so its answer wait uses `DEEP_ANSWER_TIMEOUT_MS = 500_000`;
   - when the test's waits add up to more than the config's 330 s test timeout (two turns, or one deep
     turn), call `test.setTimeout(<sum of the waits> + 30_000)` first;
   - never `waitForLoadState('networkidle')` (Playwright marks it discouraged for tests): wait on a web
     assertion for the settled UI instead, such as the sidebar list or the quota meter;
   - one assertion per expected result, with role-and-name locators (`exact: true`); select the newest answer
     with `.last()` when a spec asks more than one question.
4. Run the test (see `/e2e run`, steps 3–6) and report the verdict. Skip this step when `/e2e run` called
   Regenerate: Run's own step 3 runs the test.

## `/e2e new "<prompt>"`

1. Decide whether the prompt states the steps and the pass condition. If either is open, ask at most three
   questions with AskUserQuestion, each with a recommended answer.
2. Pick a kebab-case `<name>` naming the behaviour. Draft `test_specs/<name>.md` with these sections:
   `# <Title>`, `## Preconditions`, `## Steps` (numbered), `## Expected results` (bullets). Show it.
3. Ask the user to approve it. On changes, revise and show it again. Write nothing under `tests/` before approval.
4. Preflight, then Regenerate `<name>`.

## `/e2e run [name]`

1. Preflight.
2. For each selected spec (one, or every file in `test_specs/`): compare its `sha256sum` with its test's
   header. If the test is missing or the hash differs, say "spec changed since generation; regenerating" and
   Regenerate it first, without its step 4. If Regenerate stops without writing a test, report that and
   leave that spec out of step 3.
3. `npx playwright test` (or `npx playwright test tests/<name>.spec.ts`), then `bash check-no-password.sh`.
   If the check exits 1, report which files hold the password and stop. If it exits 2, report why it could
   not check and stop.
4. If step 3's run exited non-zero without any test failing, or `test-results/results.json` lacks an entry
   for a selected test, report "the run did not complete" with the last lines of its output and stop.
   Otherwise read `test-results/results.json`. For each test give one line:
   - passed: `✓ <title>  <duration>  saw: <what the assertions confirmed>  screenshot: <path>`;
   - failed: `✗ <title>`, then the error message, the screenshot path, the trace command
     (`npx playwright show-trace <path>/trace.zip`), the likely cause, and a call: **app bug** (the app did
     something the spec says it must not) or **test bug** (the spec's intent holds on the page but the
     test's locator or wait is wrong), with the evidence for that call from the error, the screenshot, and
     `error-context.md`.
   - skipped, flaky, timedOut, or interrupted: `<status> <title>` and the error message if any; a flaky
     test passed only on retry and counts as unverified.
   - A timeout on the answer wait and "Test timeout … exceeded" are the same case: the turn did not finish.
   - If the Error bubble inside the `Conversation` region (not the sidebar meter) reads "Daily research limit
     reached" or "Rate limit exceeded…", report "Environment problem: quota spent (429). Run `make e2e-user`
     to refill it." Do not count it as a failure, but list those tests as unverified: they have no verdict
     until they are re-run after the refill.
5. When the evidence is not enough, pause the failing test and look. Run in the background:
   `PLAYWRIGHT_HTML_OPEN=never npx playwright test tests/<name>.spec.ts --project=e2e --no-deps --debug=cli`
   (`--no-deps` skips the login, which Preflight already ran, so the pause never lands on the password form;
   `--debug=cli` opens a headed browser, so skip this step when there is no display). Wait for the `tw-…`
   session name, then `npx playwright-cli attach tw-…`, `snapshot`, `console`, `requests`. Stop the
   background test when done. Change no file.
6. End with: full report at `npx playwright show-report`. For an app bug, the user fixes the app and runs
   `/e2e run` again; for a test bug, the user edits the spec and runs `/e2e update <name>`.

## `/e2e update <name>`

Preflight, then Regenerate `<name>`.
