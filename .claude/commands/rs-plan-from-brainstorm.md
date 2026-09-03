---
description: Turn a brainstorming doc into a right-sized implementation plan, using full multi-agent review only when the change warrants it
argument-hint: <brainstorm-doc-path> [output-plan-path]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent
---

Brainstorm doc: $1
Output plan path: $2 (if empty, use `docs/plans/<date>_plan_<topic-slug>_v1.md`). `<date>` is
today's date unless the brainstorm filename carries one, in which case reuse that date.
`<topic-slug>` is **1 to 3 kebab-case words naming what the plan is about**, so the filename is
identifiable in a directory listing without opening it — e.g. `orchestrator-agent`,
`postgres-checkpointer`, `remove-prompt-logs`. Derive it from what the plan actually implements
(the brainstorm's settled decisions), not by copying the brainstorm's own topic slug verbatim —
a brainstorm can cover more ground than one plan does. If a plan for the same date and slug
already exists, increment `<N>` instead of overwriting it.

## Step 1 — Read and right-size the plan

Read the brainstorm doc in full, then read every file, module, config, and test it
names. Do not plan against the brainstorm's description of the code. Plan against the
code. Where the two disagree, the code wins and the disagreement goes in the plan.

The brainstorm records settled decisions. Treat them as decided, not as options to
reopen. Your job is to turn them into ordered, reviewable work.

Before drafting, choose the smallest planning depth that makes implementation safe:

- **Lightweight plan** -- use for a minor, contained change to one existing flow:
  a small bug fix, a narrowly scoped behavior change, or a routine local update.
  Do not inflate it into artificial commits, speculative alternatives, a migration
  section, or a multi-agent review merely because a plan was requested.
- **Standard plan** -- use for a coherent multi-file feature or refactor within
   one existing subsystem. It needs ordered file-level tasks and focused testing,
   but has no migration, high-risk interface, or cross-subsystem concern.
- **Full plan** -- use for a major update, multiple components, public interfaces,
  data or configuration migration, deletion with unknown callers, security or
  reliability risk, or a change whose parts must land in a specific order.

When uncertain, choose the full plan. Do not choose it solely because several
files change: a tightly coupled test and implementation update can still be
lightweight. If the brainstorm spans independent subsystems, split it into
separate plans that each produce independently testable software.

## Step 2 — Write the draft plan

Write a **lightweight plan** to the output path with only:

1. **Scope and non-goals** -- the intended behavior, what remains unchanged, and
   the brainstorm artifact it implements.
2. **Change steps** -- one concise, ordered group of changes with the exact files
   and concrete behavior to alter. Include code only where a non-trivial change
   would otherwise be ambiguous.
3. **Validation** -- the focused test, lint, typecheck, or manual check that
   demonstrates the change works.
4. **Required follow-up** -- only applicable documentation, configuration,
   migration, rollout, or compatibility work.

Write a **standard plan** to the output path with:

1. **Scope and non-goals** -- the intended behavior, unchanged behavior, and
   brainstorm artifact it implements.
2. **File responsibilities** -- each changed file and the responsibility it
   owns for this change.
3. **Ordered tasks** -- a small sequence of independently testable changes. For
   each task, name the files, concrete behavior, any interface it consumes or
   produces, and the focused validation command. Include code only where a
   non-trivial interface or control-flow change would otherwise be ambiguous.
4. **Test and follow-up notes** -- the assertions to add or revise and only the
   applicable documentation, configuration, migration, rollout, or compatibility
   work.

Write a **full plan** to the output path with these sections:

1. **Scope summary** — what is deleted, what is rewritten, what is deliberately kept
   and on whose stated rationale.
2. **File responsibilities** -- every created or modified file, its purpose, and
   the boundary it owns.
3. **Ordered commits** — mechanical and low-risk changes first, the riskiest rewrite
   last. For each commit: files touched, why it is safe at that point in the order,
   exact inputs consumed from earlier work, outputs relied on later, and the exact
   test command that must pass before moving on.
4. **Concrete before/after code** for every non-trivial change, as real code copied
   from and fitted to this repo, not sketches or pseudocode. Include imports. If a
   change touches a public interface, show both sides of it.
5. **Test plan** — which existing tests die, which are rewritten, which are new, and
   what each new test actually asserts.
6. **Migration and rollout notes** — schema changes, data migrations, config or env
   changes, and every documentation file this repo's own guidance requires updating
   alongside a codebase change.

Full-plan steps must be independently executable and testable. Prefer focused
checkbox steps for test, implementation, validation, and commit actions; do not
leave placeholders such as `TBD`, "add appropriate handling", or "write tests".

## Step 3 — Review by subagents

For a **lightweight plan**, self-review it before reporting back: verify it covers
every settled decision, names the exact code path and validation, has no placeholder,
and does not add unnecessary work. Do not dispatch the three reviewers unless new
information raises the plan to full scope.

For a **standard plan**, perform the same self-review, then dispatch one focused
correctness reviewer. Ask it to read the actual source and tests and identify broken
callers, behavior regressions, error-path gaps, and missing validation. Incorporate
supported findings. Do not expand to three reviewers unless new information raises
the plan to full scope.

For a **full plan**, once the plan file exists, spawn three subagents in parallel. Give each one the
brainstorm path and the plan path, and instruct each to read the actual source files
rather than trusting the plan's claims about them.

- **Correctness reviewer.** Run on Sonnet 5, medium effort. Does each commit leave the
  repo importable, runnable, and its tests passing? Hunt for deletions whose callers
  survive, survivors whose dependencies are deleted, behaviour that silently changes,
  and error or state paths that quietly differ from today.
- **Domain and framework reviewer.** Run on Sonnet 5, medium effort. For the frameworks,
  libraries, and versions this repo actually has installed, is the proposed approach the
  current correct idiom? Check the API surfaces the plan calls, the version constraints,
  and any pattern the plan copies from a reference or template.
- **Devil's advocate.** Run on Opus 5, high effort. Argue the plan is wrong. Attack the
  premises the brainstorm settled on, especially any decision justified by future work
  that is not yet scheduled. Attack every deletion by naming what breaks if the future
  never arrives. Name the cheaper plan that gets most of the benefit.

Each reviewer returns findings ranked by severity, each with a file path, a line, and a
concrete failure scenario. No style notes, no praise.

## Step 4 — Revise

For a full plan, revise it yourself with what the reviews surfaced. Add an **Open
questions and rejected objections** section recording every finding, whether you
accepted it, and why. Do not spawn a fourth agent. For a lightweight plan, correct
any self-review finding inline and add only genuine unresolved questions. For a
standard plan, correct supported reviewer findings inline and record only genuine
unresolved questions or rejected objections.

Do not start implementing. Ask the user to review and explicitly approve the written
plan before handing it to `$implement-plan`.

Report back: the plan path, whether it was lightweight, standard, or full, the task
or commit count where applicable, and the findings you accepted.
