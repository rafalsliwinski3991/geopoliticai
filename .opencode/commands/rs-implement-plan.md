---
description: Implement a written plan with TDD, tiered review, and a user checkpoint
agent: build
model: opencode-go/glm-5.3-flash
---

Plan: $1

You are the implementer and team lead. Implement only after the user approves
at the checkpoint below. For lightweight and standard plans, write the changes
yourself. For a full plan, delegate at most one genuinely independent unit at a
time. Every delegated worker and reviewer must use `opencode-go/glm-5.3-flash`.
Reviewers are read-only.

Run log: `docs/cc_logs/<plan-filename-stem>_run.md`. Create the directory when
needed; append a dated section if the log exists.

## 1. Pre-flight

Read the plan in full and identify its tier: **lightweight**, **standard**, or
**full**. If absent, infer the smallest safe tier from the real scope. Escalate
only for a concrete major, cross-component, interface, migration, or reliability
risk.

For lightweight work, verify named files, current behavior, and the focused
validation command yourself; record status and staleness in the run log. For
standard or full work, have one read-only scout compare every plan task with the
live repository. The scout must return a markdown table with `Commit`, `Status`
(`not started`, `partially applied`, or `already applied`), `Risk`
(`mechanical`, `moderate`, or `high`, with a justification for mechanical), and
`Staleness`, followed by blockers. Record its response verbatim.

When a decision depends on external library behavior, verify the installed
version and current documentation first. Local code, lockfiles, and repository
guidance are authoritative for repository behavior; record material findings.

## 2. User checkpoint

Stop after pre-flight. Show the lightweight note, or the scout table and
blockers for standard/full work. Ask the user whether to proceed and, for a
standard or full plan, where to start. Do not implement until the user answers.

## 3. Implement in order

Follow the approved plan in order, one unit at a time. Never implement two units
in parallel or reorder dependent work.

For every production behavior change, use red-green-refactor:

1. Write one focused test for the missing or changed behavior.
2. Run it and confirm it fails for the expected reason.
3. Make the smallest production change that passes it.
4. Re-run the focused test and relevant plan gate; refactor only while green.

Documentation-only, configuration-only, generated-code, and explicitly approved
throwaway-prototype work may omit a failing test; record the exception and its
validation in the run log.

For each unit, run its focused validation and planned gate, fix failures before
continuing, then commit only when both are green. Append the commit subject, gate
command, and tail of real output to the run log. Standard work receives a
per-unit audit only for moderate/high-risk units; full work receives one after
every unit.

## 4. Per-unit audit

For each required audit, use a read-only auditor to compare `git diff HEAD~1`
with the relevant plan section and live source. It must report omitted work,
unplanned work, and missing gate evidence, ranked by severity with file, line,
and failure scenario. It must mark a plan contradiction or an unimplementable
plan section as `HALT`.

Fix ordinary findings in a follow-up commit using TDD when behavior changes,
then rerun validation and the same audit. On `HALT`, stop and ask the user; do
not silently expand scope.

## 5. Final review

Review the final branch diff against the plan and tier:

- **Lightweight:** self-review scope and focused validation.
- **Standard:** one read-only correctness review.
- **Full:** independent read-only reviews for correctness, installed-framework
  API usage, and repository-guidance compliance.

Reviewers must inspect actual source and report broken callers, behavior or
error/state regressions, incorrect version assumptions, missing tests, and
required guidance updates. Fix substantive non-HALT findings, rerun relevant
validation, and rerun the review. A finding that contradicts the approved plan
is `HALT` and requires user direction.

## 6. Report

Record final review findings in the run log and show them in the response.
Report the plan path and tier, completed units and commits, validation evidence,
audits and fixes, HALTs, outstanding findings, and run-log path. Do not push or
open a pull request.

## Standing rules

- The lead is the only writer except for one independent full-plan implementation
  unit; reviewers never edit files.
- Never claim a gate, failing test, or validation result that was not run.
- When the plan and live code disagree, live code wins; record the discrepancy.
- Use `opencode-go/glm-5.3-flash` for the lead and every delegated task.
