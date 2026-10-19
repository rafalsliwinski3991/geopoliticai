---
name: unit-tests
description: "INVOKE THIS SKILL when writing, planning, or reviewing unit tests: pytest in agentic_backend/, Django TestCase in web_backend/, Vitest in frontend/chat/. Use it before naming a test, building a fake, or writing a plan's test section."
---

A unit test here is documentation that runs. A junior developer reading one test, and nothing else,
learns one rule of the code, why the rule exists, and the edge where it breaks. The suite as a whole is
the proof: every rule and every edge case the change knows about has a test that goes red when the
rule regresses.

## One test reads as one rule

- **Name is the rule.** A plain-English sentence of situation and outcome:
  `test_a_failed_forecast_gives_back_the_users_units`, `test_a_refund_never_goes_below_zero`. A
  reader who only sees the name in a failing run knows what broke. (Vitest: the `it("...")` string.)
- **Docstring is the reason.** One or two sentences on why the rule exists: the incident, the abuse it
  blocks, the user decision behind it. Say what goes wrong without the rule.
- **Arrange, act, assert.** `# Arrange`, `# Act`, `# Assert` in that order (`//` in Vitest), a
  review-blocking repo rule. When the act cannot stand apart from its assert, as a call inside
  `pytest.raises` cannot, one `# Act + Assert` section holds both. Act is one call. Assert checks the observable result: a return value, a frame the
  browser sees, a row, a call a recording fake captured.
- **One behaviour per test.** Two rules are two tests. A parametrised test is one rule over many
  inputs.
- **Named values.** `FORECAST_COST = 20`, `CHARGE_DAY = date(2026, 10, 16)`, never a bare `20` the
  reader must decode. Expected values are written by hand, never computed by the code under test.
- **Readable fakes.** One fake per seam, shared through a builder or `conftest.py`, instead of a
  closure copied into every test. A fake records what it was given (`RecordingQuota.refunds`) so the
  assert reads as a fact. A fake for a model call is **scripted**: hardcoded responses returned in
  order, every prompt recorded, and an exhausted script raises, so an unexpected extra call fails loudly.

## The edge-case catalogue

Before writing tests, list the rules the change enforces, then walk each rule through the edges below.
Every edge that applies gets its own test or its own parametrised case with an `ids=` label that reads
as the case (`ids=["source zero", "one past the last source"]`).

- **Boundaries:** zero, negative, exactly at the limit, one past it, empty, one item, duplicates.
- **Ownership and scope:** another user's row, another day's row, another thread.
- **Time:** a run that crosses midnight UTC, a timeout, a wall cap. Pin the clock by patching the
  module's own clock function; never sleep.
- **Failure paths:** each `raise` the change adds or moves; a failure during cleanup (the cleanup's
  own error must not hide the first one).
- **Interruption:** a client disconnect, a cancelled task, a stream abandoned halfway.
- **Repetition:** a retry that succeeds, a retry that fails again, and proof there is no third try.
- **Untrusted input:** model or page text that reaches a check, a log, or the user.

An edge that cannot apply says so in one line of the plan, so the reader sees it was considered.

## When a fake is not proof

A fake proves the code calls the database or framework correctly; it cannot prove the SQL or the
framework does what the code assumes. When the rule lives in SQL (a `GREATEST`, a `WHERE` on the
conflict target) or in framework behaviour (cancellation, streaming), add one integration test against
the real thing in `tests/integration_tests/`. A browser-visible rule the stack can trigger for real
(a disconnect, a full answer) also gets a plain-English e2e spec in `e2e/test_specs/`; a failure the stack cannot
be made to produce stays a unit test.

## In a plan

A plan's test section is the catalogue, written as a table: rule, then the test name that guards it,
then the file. Each new test's assertion is stated, not implied. Existing tests that die or change are
named with the reason.

## In a review

A test is defective when it cannot go red, asserts on a fake's own canned value, computes its expected
value with the code under test, or needs the code under test open to be understood. A catalogue edge
with no test is a missing test, not a style note.
