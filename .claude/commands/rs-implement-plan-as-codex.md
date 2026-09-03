---
description: "Implement a written plan through the Codex plugin with GPT-5.6 Terra at high effort, using TDD and tiered review"
argument-hint: <plan-path>
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Skill
---

Plan: $1

You are the **Codex-run coordinator**. Delegate every implementation, pre-flight,
audit, and review task through the `codex@openai-codex` Claude Code plugin. Do not
use Claude Code's native Agent tool or any named Claude subagent.

## Codex dispatch contract

Every delegated task must use this exact command shape:

```text
/codex:rescue --wait --fresh --model gpt-5.6-terra --effort high <task brief>
```

State in every task brief whether the Codex worker is an implementer or a read-only
reviewer. A reviewer must not modify files, create commits, or run destructive
commands. An implementer may modify only files needed for its assigned plan unit,
must use TDD where required below, and must commit only after its validation is
green. If the plugin, model, or high-effort setting is unavailable, stop and report
the blocker; never fall back to a Claude agent or another model.

When a decision depends on current external framework or library behavior, the
coordinator must use Context7 before dispatching: call `resolve-library-id` for
the exact library and installed version, then call `query-docs` with that
identifier. Include material verified findings in the Codex brief and run log.
Codex workers remain constrained to the Codex dispatch contract; do not replace
that contract with a native Claude agent or an unverified documentation claim.

Run log: `docs/cc_logs/<plan-filename-stem>_codex_run.md` (create `docs/cc_logs/`
if missing; it is gitignored). If that file already exists, append a new dated
section rather than overwriting it.

---

## Step 1 — Pre-flight

Read the plan in full. Identify its stated tier: **lightweight**, **standard**, or
**full**. If the plan does not name one, infer the smallest safe tier from its
actual scope. Escalate only when live code exposes a concrete major,
cross-component, interface, migration, or reliability risk; do not add process
merely because several related files change.

For a **lightweight plan**, inspect the named files, current behavior, and focused
validation command yourself, then write a short status and staleness note to the
run log. Do not dispatch a Codex scout for one contained change.

For a **standard or full plan**, dispatch a read-only Codex scout with one table row
per plan task or commit. Require these columns: identifier, `not started` /
`partially applied` / `already applied` status, `mechanical` / `moderate` / `high`
risk with justification for mechanical, staleness, and blockers. The scout must
read the actual files, not trust the plan. Copy its response into the run log.

## Step 2 — The checkpoint

**Stop here.** Show the user the direct pre-flight note for a lightweight plan, or
the Codex scout table and blockers for a standard or full plan. Ask which task or
commit to start from and whether to proceed. Do not begin implementation until the
user answers.

## Step 3 — Implementation

Walk the plan's ordered change steps, tasks, or commits in order, starting where
the user said. Never run two units at once or reorder them.

Delegate every implementation unit to a fresh Codex implementer. For a full plan,
delegate only a unit with no unresolved dependency on another unfinished unit. Give
the worker only its assigned unit, the relevant established interfaces, the plan
path, and the run-log evidence it must return. Never delegate units in parallel.

### TDD rule

For every feature, bug fix, refactor, or other production behavior change in every
plan tier, require the Codex implementer to use red-green-refactor:

1. Write one focused test for the behavior that is missing or must change.
2. Run it and confirm it fails for the expected reason, not a typo or broken setup.
3. Write the smallest production change that makes it pass.
4. Re-run the focused test and the plan's relevant gate. Refactor only while both
   remain green.

Do not allow production behavior code before its failing test. Documentation-only,
configuration-only, generated-code, and explicitly approved throwaway-prototype
work are exceptions; require the worker to record the exception and its validation
in the run log.

For every unit, require the Codex implementer to:

1. Follow the TDD rule when production behavior changes; otherwise make the exact
   planned change.
2. Run the focused validation and plan gate.
3. Commit only after both are green.
4. Return the commit subject, commands run, output summary, changed files, and any
   concerns. Append the real command-output tail to the run log.
5. For a standard plan, request the Step 4 audit when the scout marked the unit
   `moderate` or `high`. For a full plan, request it after every unit.

## Step 4 — Per-unit audit

Dispatch a fresh read-only Codex auditor. Give it the plan path, the unit section,
and `git diff HEAD~1`. Require severity-ranked findings with file and line,
concrete failure scenario, plan omissions, unplanned work, and whether the logged
gate evidence is real. A plan contradiction is `HALT`.

- For ordinary findings, dispatch a fresh Codex implementer to fix them, requiring
  TDD for behavior changes, green validation, a follow-up commit, and run-log
  evidence. Then dispatch a fresh Codex auditor against the fix diff.
- For `HALT`, stop and report it to the user. Do not settle a scope contradiction
  without the user's approval.

## Step 5 — Final review

Review the branch diff from the commit at the start of the run to `HEAD` according
to the plan tier:

- **Lightweight plan** -- perform the final diff review yourself against the scope
  and focused validation. Do not dispatch Codex review unless concrete evidence
  escalates the work.
- **Standard plan** -- dispatch one read-only Codex correctness reviewer.
- **Full plan** -- dispatch three separate read-only Codex reviewers, sequentially:
  correctness, framework/version compatibility, and guidance compliance.

Each Codex reviewer must use the dispatch contract and return only severity-ranked
findings grounded in the real source and diff. The guidance reviewer must check
whether `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` were
updated when required. For a framework/version finding, the coordinator must
first verify the relevant current documentation through Context7 and include the
result in the review brief.

Fix substantive findings before completion. Dispatch a fresh Codex implementer for
each fix batch, require focused validation and the relevant gate, then dispatch the
same type of reviewer on the fix diff. Treat a finding that contradicts the
approved plan as `HALT`.

## Step 6 — Report

Write all Codex review findings to the run log and also show them to the user. For
a lightweight plan, record the coordinator's final self-review instead.

Report the plan path and tier, tasks or commits made, Codex audits and reviews,
fixes applied, any `HALT`, outstanding findings not acted on, and the run-log path.
Do not push or open a pull request.

## Standing rules

- Every dispatched worker uses `gpt-5.6-terra` with `--effort high` through
  `/codex:rescue`; no exceptions and no fallback model.
- Never run a native Claude Code subagent for this command.
- Never mark a behavior change complete without a recorded failing focused test,
  green focused validation, and the applicable gate.
- Never mark a commit complete on a gate that did not run.
- Where the plan and live code disagree, record the disagreement in the run log.