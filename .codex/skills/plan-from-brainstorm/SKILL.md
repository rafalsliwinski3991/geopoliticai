---
name: plan-from-brainstorm
description: Turn a settled brainstorming artifact into a reviewed, repository-grounded implementation plan. Use only when explicitly invoked with `$plan-from-brainstorm`.
---

# Plan from Brainstorm

Use this skill after design decisions have been made and before code changes
begin. The first argument is a brainstorming document path; an optional second
argument is the plan output path.

## Workflow

1. Read the complete brainstorming artifact. Treat its recorded decisions as
   settled unless they conflict with the current repository.
2. Resolve the output path. When none is supplied, write beside the source in
   `docs/brainstorming/` using the next available `*_plan_v<N>.md` name.
3. Inspect the affected code and guidance before drafting. Use the local
   `explorer` role for focused, read-only repository discovery when useful.
   The plan must reflect what exists now, not assumptions from the brainstorm.
4. Write a self-contained plan with:
   - a scope summary and explicit non-goals;
   - ordered, independently reviewable commits;
   - concrete file-level changes, including representative before/after
     interfaces or control flow where that removes ambiguity;
   - tests and validation gates for each relevant change;
   - migration, rollout, documentation, and compatibility notes when needed.
5. Ask the local `critic` role to review the plan for correctness, missing
   repository constraints, unsafe assumptions, and test gaps. Incorporate
   supported findings.
6. Add an **Open questions and rejected objections** section explaining any
   unresolved decision or review finding that was deliberately not adopted.

Do not implement the plan, alter application code, or create a pull request.
Report the written plan path and the validation/review performed.
