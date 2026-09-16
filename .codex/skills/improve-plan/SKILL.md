---
name: improve-plan
description: Review and rewrite an existing implementation plan as a new, repository-grounded version. Use only when explicitly invoked with `$improve-plan`.
---

# Improve Plan

The first argument is an existing plan path. Never overwrite that source plan.

## Workflow

1. Read the complete source plan and inspect the present repository state.
   Identify which planned changes are already applied, stale, or blocked.
   Use the local `explorer` role for focused read-only discovery when useful.
2. Derive the destination by incrementing the source filename's version:
   `*_v1.md` becomes `*_v2.md`. If it has no version suffix, append `_v2`.
   Do not overwrite an existing file; choose the next unused version.
3. Have the local `critic` role review the source plan against the codebase for
   correctness, completeness, sequencing, repository guidance, compatibility,
   and test coverage.
4. Write a standalone revised plan at the new path. It must include its own
   scope, non-goals, ordered commit-sized steps, concrete files and interfaces,
   validation gates, and rollout or documentation work where relevant.
5. Finish with a **Changelog from previous plan** and an **Open questions and
   rejected objections** section. Preserve useful decisions from the old plan,
   but remove recommendations disproven by the current repository.

### Stacked pull-request planning

Make the revised plan directly usable by `rs-implement-plan` and
`rs-create-stacked-prs`:

- Carry forward or repair the trunk/base branch and stable stack slug. Use the
   repository default branch unless the user specifies another base.
- Keep a lightweight plan as one unit when it is genuinely contained. For
   standard or full plans, each ordered task or commit must be one independently
   reviewable stack unit; do not split inseparable work merely to create more
   branches.
- For every revised unit, record its proposed branch name, parent branch or
   unit, exact files, consumed inputs, produced outputs, dependencies, focused
   validation, and gate command. Order units bottom-to-top so each is usable
   without uncommitted work from another unit.
- Preserve valid existing boundaries and order. If changes must be split or
   reordered for independent review, record that decision in the changelog.
- State that implementation creates one linear commit per unit. The separate
   `rs-create-stacked-prs` workflow adopts the branches, verifies them with
   `gh stack view`, and submits draft or ready-for-review PRs; planning itself
   does not push, create, merge, or rewrite pull requests.

Do not implement the plan, modify application code, or alter the original
plan. Report the new plan path and the review findings incorporated.
