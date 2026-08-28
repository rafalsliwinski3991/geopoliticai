---
description: Turn a brainstorming doc into a detailed implementation plan, then have three subagents review it from different angles
argument-hint: <brainstorm-doc-path> [output-plan-path]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent
---

Brainstorm doc: $1
Output plan path: $2 (if empty, use `docs/plans/<same-date-and-version-as-the-brainstorm>_plan_v1.md`; if the brainstorm filename carries no date, use today's date in the repo's existing `docs/plans/` naming style)

## Step 1 — Read

Read the brainstorm doc in full, then read every file, module, config, and test it
names. Do not plan against the brainstorm's description of the code. Plan against the
code. Where the two disagree, the code wins and the disagreement goes in the plan.

The brainstorm records settled decisions. Treat them as decided, not as options to
reopen. Your job is to turn them into ordered, reviewable work.

## Step 2 — Write the draft plan

Write the plan to the output path with these sections:

1. **Scope summary** — what is deleted, what is rewritten, what is deliberately kept
   and on whose stated rationale.
2. **Ordered commits** — mechanical and low-risk changes first, the riskiest rewrite
   last. For each commit: files touched, why it is safe at that point in the order, and
   the exact test command that must pass before moving on.
3. **Concrete before/after code** for every non-trivial change, as real code copied
   from and fitted to this repo, not sketches or pseudocode. Include imports. If a
   change touches a public interface, show both sides of it.
4. **Test plan** — which existing tests die, which are rewritten, which are new, and
   what each new test actually asserts.
5. **Migration and rollout notes** — schema changes, data migrations, config or env
   changes, and every documentation file this repo's own guidance requires updating
   alongside a codebase change.

## Step 3 — Review by subagents

Once the plan file exists, spawn three subagents in parallel. Give each one the
brainstorm path and the plan path, and instruct each to read the actual source files
rather than trusting the plan's claims about them.

- **Correctness reviewer.** Does each commit leave the repo importable, runnable, and
  its tests passing? Hunt for deletions whose callers survive, survivors whose
  dependencies are deleted, behaviour that silently changes, and error or state paths
  that quietly differ from today.
- **Domain and framework reviewer.** For the frameworks, libraries, and versions this
  repo actually has installed, is the proposed approach the current correct idiom? Check
  the API surfaces the plan calls, the version constraints, and any pattern the plan
  copies from a reference or template.
- **Devil's advocate.** Argue the plan is wrong. Attack the premises the brainstorm
  settled on, especially any decision justified by future work that is not yet
  scheduled. Attack every deletion by naming what breaks if the future never arrives.
  Name the cheaper plan that gets most of the benefit.

Each reviewer returns findings ranked by severity, each with a file path, a line, and a
concrete failure scenario. No style notes, no praise.

## Step 4 — Revise

Revise the plan yourself with what the reviews surfaced. Add an **Open questions and
rejected objections** section recording every finding, whether you accepted it, and
why. Do not spawn a fourth agent. Do not start implementing.

Report back: the plan path, the commit count, and the findings you accepted.
