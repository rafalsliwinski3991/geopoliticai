---
description: Implement a written plan with TDD at every tier and review proportional to its lightweight, standard, or full scope
argument-hint: <plan-path>
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent
---

Plan: $1

You are the **implementer** and the team lead. For lightweight and standard plans, you are the only
writer in this run. For a full plan, you may delegate one genuinely independent task at a time to a
fresh implementer agent; otherwise you remain the writer. Every review agent is read-only and exists
to check the work.

Run log: `docs/cc_logs/<plan-filename-stem>_run.md` (create `docs/cc_logs/` if missing; it is
gitignored). If that file already exists, append a new dated section rather than overwriting it.

---

## Step 1 — Pre-flight

Read the plan in full. Identify its stated tier: **lightweight**, **standard**, or **full**. If the
plan does not name one, infer the smallest safe tier from its actual scope. Escalate only when live
code exposes a concrete major, cross-component, interface, migration, or reliability risk; do not
add process merely because several related files change.

For a **lightweight plan**, verify the named files, current behavior, and focused validation command
yourself, then write a short status and staleness note to the run log. Do not spawn a scout for one
contained change.

When implementation or review depends on current external framework or library
behavior, use Context7 before changing code: call `resolve-library-id` for the
exact library and installed version, then call `query-docs` with that identifier.
Record any material documentation result in the run log. The checked-out code,
lockfile, and repository guidance remain authoritative for local behavior.

For a **standard or full plan**, spawn a single teammate named `scout` using the `preflight-scout` agent
type, and give it the plan path and this brief:

> Compare the plan at `<path>` against this repository as it is right now. Read the actual files the
> plan names — never trust the plan's description of the code. Produce **one markdown table, one row
> per plan task or commit**, with exactly these columns:
>
> - **Commit** — the plan's own identifier or heading for it.
> - **Status** — `not started` / `partially applied` / `already applied`, decided by reading the
>   files, not the plan.
> - **Risk** — `mechanical` / `moderate` / `high`. Every `mechanical` verdict must be followed, in
>   the same cell, by a one-line justification naming what you actually checked to reach it. A
>   `mechanical` verdict with no justification is invalid.
> - **Staleness** — moved paths, changed line numbers, dependency versions that differ from what the
>   plan assumes, whether `main` has advanced since the plan was written, or `—` if clean.
>
> Below the table, list any **blockers**: plan sections that cannot be implemented as written against
> the current code. Write nothing to disk and change nothing. Return the table and the blockers as
> your message to the lead — an idle notification carries no output, so you must send it explicitly.

Write the scout's table and blockers into the run log verbatim.

## Step 2 — The checkpoint

**Stop here.** This is the only scheduled stop in the run.

For a **lightweight plan**, show the direct pre-flight note and ask whether to proceed. For a
**standard or full plan**, show the scout's table and blockers, then ask which task or commit the
run should start from and whether to proceed. Do not begin implementing until the user answers. If
the user does not respond, the run does not start.

## Step 3 — Implementation

Walk the plan's ordered change steps, tasks, or commits **in order**, starting where the user said.
Never work on two at once, and never reorder them — the ordering is the plan's safety property.

Lightweight and standard plans are implemented directly by the lead. The standard plan receives exactly
one final `correctness-lens` review. For a full plan, delegate a unit only when it has no unresolved
dependency on another unfinished unit; give the fresh implementer only that unit's requirements,
relevant established interfaces, and the run-log contract. It must use this command's TDD rule, run
the planned validation, commit only while green, and report its evidence to the lead. Never delegate
two implementation units in parallel.

### TDD rule

For every feature, bug fix, refactor, or other production behavior change in every plan tier, use
red-green-refactor:

1. Write one focused test for the behavior that is missing or must change.
2. Run it and confirm it fails for the expected reason, not due to a typo or broken setup.
3. Write the smallest production change that makes it pass.
4. Re-run the focused test and the plan's relevant gate. Refactor only while both remain green.

Do not write production behavior code before its failing test. Documentation-only, configuration-only,
generated-code, and explicitly approved throwaway-prototype work are exceptions; record the exception
and the validation used in the run log. A test that passes before the change does not establish the
needed behavior; revise it until it fails correctly.

For each unit of work:

1. Follow the TDD rule when the unit changes production behavior; otherwise make the change exactly
  as the plan specifies.
2. Run the plan's focused validation and gate command (`make test`, `make lint`, whatever the plan
  names).
3. **Commit only once the validation and gate are green.** A red gate is fixed before committing, never after. Fix
   forward applies to *reviewer findings only*, never to gate failures.
4. Append to the run log: the commit subject, the gate command you ran, and the **tail of its real
   output**. This is the evidence that the gate actually ran; a run log entry without it is treated
   as a skipped gate.
5. For a standard plan, run Step 4 only when the scout marked the unit `moderate` or `high`. For a
   full plan, run Step 4 after every unit. A lightweight plan does not require a per-unit audit unless
   implementation reveals a concrete risk that escalates its tier.

## Step 4 — Per-unit audit

Spawn a teammate named `auditor` using the `commit-auditor` agent type, with this brief:

> Read `git diff HEAD~1` and the plan section at `<path>` that this commit implements. Report:
> (a) anything the plan asked for that the diff does not do; (b) anything the diff does that the plan
> did not ask for; (c) whether the run log entry for this commit records a real gate command and its
> output. Read the source files themselves rather than trusting either the plan or the diff summary.
> Rank findings by severity, each with a file path, a line, and a concrete failure scenario. No style
> notes, no praise. Message your findings to the lead directly.
>
> One finding type is **halt-severity**: a plan contradiction — the diff does something the plan never
> asked for, or the plan section is unimplementable as written against the current code. Mark those
> `HALT`. Everything else is ordinary.

Reuse the same auditor across units by messaging it rather than spawning a new one each time.

Then:

- **Ordinary findings** → fix them yourself as a follow-up commit, using the TDD rule when behavior
  changes, then gate and log it like any other. Re-run the same auditor against the fix diff before
  moving on. Record in the run log what was found and what you did.
- **A `HALT` finding** → stop the run, report it to the user, and wait. This is a scope question and
  it is not yours to settle.

## Step 5 — Final review

After the last plan unit, review the result against the branch diff
(`git diff <base>...HEAD`, base being the commit the run started from) according to its tier:

- **Lightweight plan** -- review the final diff yourself against its scope and focused validation.
  Do not spawn a lens unless a concrete finding escalates the work.
- **Standard plan** -- spawn exactly one `correctness-lens` using the correctness brief below.
- **Full plan** -- **you** spawn all three lenses in parallel. A teammate cannot spawn teammates, so
  this fan-out has to come from here.

- `correctness-lens` — broken call sites, deletions whose callers survive, behaviour that silently
  changed, error and state paths that differ from before.
- `framework-lens` — is this the current correct idiom for the versions **actually installed** in
  this repo? Check the API surfaces the diff calls and the version constraints it assumes.
  Use Context7's `resolve-library-id` and `query-docs` when current external
  documentation is needed.
- `guidance-compliance-lens` — did this change require updating `CLAUDE.md`, `AGENTS.md`, and
  `.github/copilot-instructions.md` per this repo's own rule, and do those files still describe the
  code truthfully?

Give each spawned lens the plan path, the diff range, and an instruction to **message its findings to
the lead** and to read the real source files. A standard plan receives only the first brief. If a
lens should use the repo's review tooling, say so in its spawn prompt — a `skills:` field in an agent
definition is ignored for teammates, so it cannot be preloaded.

Fix substantive findings before completing the run. For a behavior change, use the TDD rule; in all
cases rerun the focused validation and applicable gate. Then rerun the same lens on the fix diff. A
finding that contradicts the approved plan is a `HALT`; stop and ask the user rather than silently
expanding scope.

## Step 6 — Report

Write any lens findings into the run log, then **also print them to the terminal**. The run log is
gitignored, so anything that exists only there is invisible to any later reader. For lightweight
plans, record the lead's final self-review instead.

Report to the user: the plan path and tier, tasks or commits made, units audited and what the audits
found, what was fix-forwarded, any `HALT` you hit, the outstanding applicable review findings you did
**not** act on, and the run log path.

Do not push. Do not open a pull request.

---

## Standing rules

- You are the only writer. If you catch yourself asking a review agent to change something, stop —
  they have no write tools and the request will fail.
- Reviewers must be told to message their findings. An idle notification tells you a teammate
  stopped; it does not carry its output.
- Never mark a commit done on a gate you did not run.
- Never mark a behavior change done without recording the failing focused test, green validation, and
  applicable gate.
- Where the plan and the code disagree, the code wins, and the disagreement goes in the run log.
