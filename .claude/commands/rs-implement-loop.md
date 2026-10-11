---
description: Implement a brainstorm's design in a loop that ends when the user's definition of done holds, then review it and open a pull request
argument-hint: "<brainstorm-path> [slice]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

Brainstorm: $ARGUMENTS

Implement a brainstorm's design in a loop that ends when the user's definition of done holds. The first argument is the artifact path (`docs/brainstorming/*.md`); the rest, if any, names the slice to build. You write the code, the tests, and the loop file.

The loop file is `docs/harness_logs/<slug>-loop/loop.md` (gitignored; `<slug>` is the artifact's topic slug). It holds the definition of done and one entry per iteration. Trust it and `git log` over your recollection. If it already exists, read it and resume at Step 4.

---

## Step 1 — Read

Read the artifact in full and the code its decisions touch. Settled decisions are fixed. Carried flags are yours to resolve by reading, or to put to the user in Step 2. The slice is the argument's, else the whole Target design.

## Step 2 — Clarify and define done

Ask before writing code. Use your harness's question tool, or a numbered chat list, and put every question in one round. Give each question a worked example, your recommended answer, and what each answer changes.

1. **Scope.** The slice, restated in one line, and what is out of scope.
2. **Definition of done.** Propose a checklist from the artifact. Each item is a **check**: a command whose exit code decides, or an observable the user confirms by name. Examples: `make test` exits 0; `uv run pytest agentic_backend/tests/unit_tests/foo/test_bar.py` passes; "the user reads the new response and agrees". An item nobody can check ("works well") goes back for rewording until it is checkable.
3. **Budget.** Maximum iterations (recommend 8).
4. **Delivery.** Open a pull request when done? Which base branch?
5. **Open flags.** Each carried flag you could not resolve by reading.

Then restate scope, the checklist as a table (item, check, owner: agent or user), the budget, and delivery. Wait for the user's explicit approval. The approved checklist is the loop's exit; only the user changes it afterwards.

If your harness has a goal or stop-condition feature (Claude Code: `/goal <condition>`), give the user the one-line condition to set, so the harness itself holds the loop open.

## Step 3 — Branch and loop file

Cut `loop/<slug>` from the current branch. Create the loop file with the approved table, the budget, and an empty iteration log.

## Step 4 — Loop

Repeat until the exit test (item 6) passes:

1. Pick the smallest slice that turns one unmet checklist item green.
2. Red: write the failing test and watch it fail.
3. Green: write the smallest code that passes it, then run the narrowest check that covers it.
4. Gate: the repo's tests and lint from `CLAUDE.md` pass, then commit.
5. Log the iteration: what changed, and each check's command with its result.
6. Exit test: run every checklist check now. The loop exits when each agent check passes in this run and the user has confirmed each user check in their own words. Otherwise start the next iteration.

An item is met when its check ran in the current iteration and passed; the log quotes the command and the result.

Stop and report when the budget is spent, or when two consecutive iterations turn no item green. Say what you tried, and ask the user whether to change the checklist, extend the budget, or take another approach.

## Step 5 — Close

1. Run `/rs-code-review` on the branch, fix its findings, and re-run every checklist check.
2. Update `CLAUDE.md` when the application codebase changed, as it requires.
3. When the user asked for delivery, push and open one pull request against the chosen base. Its description carries the checklist with each item's evidence.
4. Report: the checklist table with evidence, the branch, the pull request URL.
