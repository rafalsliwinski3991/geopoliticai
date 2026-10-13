---
description: Implement a brainstorm's design in a loop that ends when the user's definition of done holds, on a draft pull request reviewed each iteration
argument-hint: "<brainstorm-path> [slice]"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent, Skill, AskUserQuestion
---

Brainstorm: $ARGUMENTS

Implement a brainstorm's design in a loop that ends when the user's definition of done holds. The first argument is the artifact path (`docs/brainstorming/*.md`); the rest, if any, names the slice to build. You write the code, the tests, and the loop file.

The loop file is `docs/harness_logs/claude-code/<YYYYMonDD>_<slug>/loop.md` (gitignored; `<slug>` is the artifact's topic slug). It holds the definition of done and one entry per iteration, and is exempt from `docs/harness_logs/TEMPLATE.md`: no header, no metrics table. Trust it and `git log` over your recollection. If it already exists, read it, check out the branch it records, and resume at Step 4.

---

## Step 1 — Read

Read the artifact in full and the code its decisions touch. Settled decisions are fixed. Carried flags are yours to resolve by reading, or to put to the user in Step 2. The slice is the argument's, else the whole Target design. Stop and ask if the artifact does not exist, if it has no Target design and no slice was given, or if the slice matches nothing in it.

## Step 2 — Clarify and define done

Ask before writing code. Use your harness's question tool, or a numbered chat list, and put every question in one round. Give each question a worked example, your recommended answer, and what each answer changes.

1. **Scope.** The slice, restated in one line, and what is out of scope.
2. **Definition of done.** Propose a checklist from the artifact. Each item is a **check**: a command whose exit code decides, or an observable the user confirms by name. Examples: `make test` exits 0; `cd agentic_backend && uv run pytest tests/unit_tests/foo/test_bar.py` passes; "the user reads the new response and agrees". An item nobody can check ("works well") goes back for rewording until it is checkable.
3. **Budget.** Maximum iterations (recommend 8).
4. **Base and delivery.** Ask explicitly for the base branch: `loop/<slug>` starts from it and a draft pull request against it opens once the branch is cut (recommend the repo's default branch). When the loop exits, turn the draft pull request over for final review?
5. **Open flags.** Each carried flag you could not resolve by reading.

Then restate scope, the checklist as a table (item, check, owner: agent or user), the budget, the base branch, and delivery. Wait for the user's explicit approval. The approved checklist is the loop's exit; only the user changes it afterwards.

If your harness has a goal or stop-condition feature (Claude Code: `/goal <condition>`), give the user the one-line condition to set, so the harness itself holds the loop open.

## Step 3 — Branch and loop file

Stop and ask if the working tree has uncommitted changes or `loop/<slug>` already exists. Otherwise cut `loop/<slug>` from the approved base branch. Create the loop file with the approved table, the budget, the branch name, and an empty iteration log. Then open one draft pull request from `loop/<slug>` against the approved base and record its URL in the loop file. The draft PR belongs to the loop itself, not to the delivery choice in Step 2: review runs on it whether or not the user later asks for delivery.

Run every agent check once and log its result. Each should fail now. If one already passes, stop and ask the user to reword or drop it before Step 4; it cannot close the loop as is.

## Step 4 — Loop

Repeat until the exit test (item 6) passes:

1. Pick the smallest slice that turns one unmet checklist item green.
2. Red: write the failing test and watch it fail.
3. Green: write the smallest code that passes it, then run the narrowest check that covers it.
4. Gate: run the suites, as `CLAUDE.md` gives them, for each area the change touched: `make test` and `make lint` from `agentic_backend/`; `make test-web-backend` from the root (needs the dev Postgres); `npm test` from `frontend/chat/`. When they pass, commit. Log a suite that cannot run as not run, never as passed.
5. Log the iteration: what changed, and each check's command with its result.
6. Exit test: run every agent check now, and ask the user for a verdict on each unmet user check, quoting the reply in the log. The loop exits when each agent check passes in this run and the user has confirmed each user check in their own words. Otherwise start the next iteration.

An item is met when its check ran in the current iteration and passed; the log quotes the command and the result.

Stop and report when the budget is spent, or when two consecutive iterations turn no agent check green (user checks do not count toward this). Say what you tried, and ask the user whether to change the checklist, extend the budget, or take another approach.

## Step 5 — Close

1. Push so the draft PR carries every iteration, then run `/rs-code-review` on it, fix the findings it posts — each arrives as a PR comment: apply it with the loop's red-green workflow, or hand it to `/rs-address-feedback` — and re-run every checklist check.
2. Update `CLAUDE.md` when the application codebase changed, as it requires.
3. Re-run the Step 4 gate, then commit the review fixes and any `CLAUDE.md` change. Ask the user to confirm each user check again against this committed version.
4. When the user asked for delivery, verify the tree is clean, push, and mark the draft pull request ready for review against the chosen base. Its description carries the checklist with each item's evidence.
5. Report: the checklist table with evidence, the branch, the pull request URL.
