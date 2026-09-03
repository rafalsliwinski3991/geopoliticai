---
name: implement-plan
description: Implement an approved repository plan with explicit checkpoint, validation, and review. Use only when explicitly invoked with `$implement-plan`.
---

# Implement Plan

The first argument is a reviewed implementation-plan path.

## Workflow

1. Read the whole plan and inspect the relevant current code. Use the local
   `explorer` role as a read-only preflight scout when useful. Reconcile plan
   assumptions with the repository; code and repository guidance are the
   source of truth.
2. Present a short execution summary, any material drift, and the exact
   validation gates. Stop for one explicit user approval before making writes.
3. After approval, use the local `builder` role to implement the plan in its
   stated dependency order. Keep changes scoped to the approved plan; do not
   silently expand the task.
4. Run the plan's tests and the repository-required formatting, linting, and
   checks that apply. Fix failures caused by the changes. Record significant
   command results in `docs/cc_logs/` when the repository convention requires
   an implementation log.
5. Ask the local `critic` role for a final correctness and regression review;
   request an additional focused review before or after any high-risk change.
   Address substantiated findings, then rerun affected checks.
6. Report changed files, validation results, remaining limitations, and any
   deviations from the approved plan. Do not push, create a pull request, or
   perform external actions unless the user separately requests them.

If a material ambiguity, missing authority, or external dependency blocks a
safe implementation, stop and ask the user rather than guessing.
