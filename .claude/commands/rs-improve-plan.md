---
description: Audit a written plan against the current repo and rewrite it as a new, self-contained, right-sized version with a changelog
argument-hint: <plan-path>
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent
---

Plan: $1

You are the **auditor and reviser** and the team lead. You are the only agent in this run that
writes. Every other agent you spawn is read-only and exists to check the plan, never to change it.

Run log: `docs/cc_logs/<plan-filename-stem>_improve_run.md` (create `docs/cc_logs/` if missing; it is
gitignored). If that file already exists, append a new dated section rather than overwriting it.

---

## Step 0 — Resolve the new version path

Read `$1`'s filename. It must end `_v<N>.md`; if it doesn't, treat it as `v1` for numbering purposes
but do not rename it. The new path is the same directory and stem with `_v<N+1>.md`. If that path
already exists, keep incrementing until it doesn't.

Do not create the new file yet — it is written once, complete, at the end of Step 3.

## Step 1 — Read

Read the plan in full. Then read every file, module, config, and test it names. Do not audit against
the plan's description of the code — audit against the code. Where they disagree, the code wins, and
every disagreement becomes a changelog entry in the new version, not a silent fix.

Identify the plan's stated tier: **lightweight**, **standard**, or **full**. If it
does not name one, infer the smallest safe tier from its scope. Preserve that tier
unless the live code reveals a concrete risk that requires escalation; do not enlarge
the plan merely because it is being reviewed. A lightweight plan is a minor contained
change, a standard plan is coherent multi-file work within one subsystem, and a full
plan covers major, risky, cross-component, interface, migration, or order-dependent
work. Record any escalation and its evidence in the changelog.

## Step 2 — Pre-flight scout

For a **lightweight plan**, inspect the named files and focused validation yourself.
Write a short status and staleness note into the run log; do not spawn a scout just to
produce one row for one contained change.

For a **standard or full plan**, spawn a single teammate named `scout` using the `preflight-scout` agent type, and give it the plan
path and this brief:

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
>   plan assumes, whether the plan's base branch has advanced since it was written, or `—` if clean.
>
> Below the table, list any **blockers**: plan sections that can no longer be implemented as written
> against the current code. Write nothing to disk and change nothing. Return the table and the
> blockers as your message to the lead — an idle notification carries no output, so you must send it
> explicitly.

Write the scout's table and blockers into the run log verbatim.

If every task or commit comes back `already applied` with no blockers, stop here: report to the user that
the plan appears fully implemented and ask whether they still want a new version (for example, to
record that fact) before spawning anything else in Step 3.

## Step 3 — Parallel critical review

For a **lightweight plan**, self-review the proposed change against the live code.
Check its exact behavior, focused validation, and applicable guidance. Do not dispatch review
agents unless a concrete discovery raises the plan's tier.

For a **standard plan**, spawn only `correctness-lens`. Give it the brainstorm or context doc this
plan was built from (if named), the plan path, and the scout's table. It must read actual source
files and return only severity-ranked correctness, regression, error-path, or test-gap findings.

For a **full plan**, spawn three teammates in parallel. Give each the brainstorm or context doc this plan was built from
(if the plan names one), the plan path, and the scout's table, and instruct each to read the actual
source files rather than trusting the plan's or the scout's claims about them. Unlike a post-run
review, there is no diff yet — these agents review the plan's **proposed** commits and code blocks
against the live repository, as if deciding whether to approve them before a single line is written.

- **`correctness-lens`** (agent type `correctness-lens`). Brief: For every commit in the plan, would
  applying it exactly as written leave the repo importable, runnable, and its tests passing? Hunt for
  proposed code that references symbols, signatures, or files that don't exist or don't match; plan
  steps that assume a state the scout's table says isn't there; deletions whose callers would
  survive; commits that depend on a later commit's output; error or state paths the plan's code would
  quietly handle differently than today.
- **`framework-lens`** (agent type `framework-lens`). Brief: For the frameworks, libraries, and
  versions actually installed in this repo right now, is the plan's approach still the current
  correct idiom? Check every API surface the plan's code blocks call, every version constraint the
  plan assumes, and whether a newer or older installed version has moved the ground since the plan
  was written.
- **`guidance-compliance-lens`** (agent type `guidance-compliance-lens`). Brief: Read `AGENTS.md`,
  `CLAUDE.md`, and `.github/copilot-instructions.md` as they exist right now. Does the plan's
  migration/rollout section correctly identify every one this repo's own rules require updating, and
  does it describe changes that are still accurate given what these files currently say? Also flag
  any place the plan itself now contradicts this repo's standing guidance.

Each must message its findings to the lead directly (an idle notification carries no output). Each
finding: ranked by severity, with a file path, a line (in the plan or in the source), and a concrete
failure scenario. No style notes, no praise, no summary of what the plan does well.

Write every lens's findings into the run log verbatim.

## Step 4 — Revise into a new, complete version

Write the new version at the path resolved in Step 0. **It must stand alone.** Someone reading only
this file, never opening the previous version, must get the full picture — do not write "see v1 for
the rest" or omit a commit because it didn't change. Carry forward everything from the previous
version that the scout and the lenses did not invalidate, and rewrite everything they did.

The new version keeps the previous version's tier and appropriate section structure: lightweight
plans keep scope, change steps, validation, and applicable follow-up; standard plans keep scope,
file responsibilities, ordered tasks, and test/follow-up notes; full plans keep scope summary,
file responsibilities, ordered commits with before/after code, test plan, migration and rollout
notes, and open questions. Add one more section immediately after the title:

**Changelog (v`<N>` → v`<N+1>`)** — one entry per substantive change from this round, each stating
what changed, which finding drove it (scout staleness, or a named lens finding), and why. Include
entries for commits marked `already applied` or `partially applied` by the scout and how the new
version accounts for that (mark them done and adjust the remaining ordering, rather than re-proposing
finished work). If a finding was surfaced but you rejected it, say so here with the reason, the same
way `rs-plan-from-brainstorm`'s "Open questions and rejected objections" section works — do not silently
drop a reviewer's finding.

Do not start implementing. Do not spawn a fourth agent.

## Step 5 — Report

Report to the user: the previous plan path, the new plan path, the version bump, the scout's
top-line status (how many tasks or commits are already applied / partially applied / not started),
the plan tier, how many findings each applicable lens raised and how many you accepted, and the run
log path.

---

## Standing rules

- You are the only writer. If you catch yourself asking a review agent to change something, stop —
  they have no write tools and the request will fail.
- Reviewers must be told to message their findings. An idle notification tells you a teammate
  stopped; it does not carry its output.
- Where the plan and the code disagree, the code wins, and the disagreement goes in the changelog.
- The new version is a complete replacement, never a diff or a pointer back to the old one.
- Never claim a finding was addressed unless the new version's text actually reflects it.
