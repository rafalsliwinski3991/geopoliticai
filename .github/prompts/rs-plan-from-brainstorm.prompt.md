---
name: rs-plan-from-brainstorm
description: "Turn a brainstorming doc into a right-sized implementation plan, using full multi-pass review only when the change warrants it"
argument-hint: <brainstorm-doc-path> [output-plan-path]
agent: agent
tools: ["context7/*", "edit", "execute", "read", "search", "web"]
---

Input: the text the user typed after the command.
Brainstorm doc: the first path in the input.
Output plan path: the second path in the input (if absent, use `docs/plans/<date>_plan_<topic-slug>_v1.md`). `<date>` is
today's date unless the brainstorm filename carries one, in which case reuse that date.
`<topic-slug>` is **1 to 3 kebab-case words naming what the plan is about**, so the filename is
identifiable in a directory listing without opening it — e.g. `orchestrator-agent`,
`postgres-checkpointer`, `remove-prompt-logs`. Derive it from what the plan actually implements
(the brainstorm's settled decisions), not by copying the brainstorm's own topic slug verbatim —
a brainstorm can cover more ground than one plan does. If a plan for the same date and slug
already exists, increment `<N>` instead of overwriting it.

## Step 1 — Read and right-size the plan

Read the brainstorm doc in full, then read every file, module, config, and test it
names. Plan against the
code. Where the two disagree, the code wins and the disagreement goes in the plan.

The brainstorm records settled decisions. Treat them as decided, not as options to
reopen. Your job is to turn them into ordered, reviewable work.

When a proposed change depends on a current external framework or library API,
resolve its exact library and version through Context7's `resolve-library-id`,
then verify the relevant behavior with `query-docs`. Plan against the verified
documentation and the installed version, not memory. Do not query Context7 for
repository-local behavior that the checked-out code or guidance already answers.

Use Context7 for library documentation only. For implementation patterns, prior
art, and API guidance outside library docs -- vendor guides, tech blogs, GitHub
repositories or issues -- search the web and read the sources. Cite every web source the plan relies on, and prefer official sources when
they conflict with others.

When a question blocks a safe plan and neither the code nor the brainstorm answers
it, ask the user in chat and wait for the answer instead of guessing. Leave settled
decisions this way; ask only about genuine gaps.

Before drafting, choose the smallest planning depth that makes implementation safe:

- **Lightweight plan** -- use for a minor, contained change to one existing flow:
  a small bug fix, a narrowly scoped behavior change, or a routine local update.
  Do not inflate it into artificial commits, speculative alternatives, a migration
  section, or a multi-pass review merely because a plan was requested.
- **Standard plan** -- use for a coherent multi-file feature or refactor within
   one existing subsystem. It needs ordered file-level tasks and focused testing,
   but has no migration, high-risk interface, or cross-subsystem concern.
- **Full plan** -- use for a major update, multiple components, public interfaces,
  data or configuration migration, deletion with unknown callers, security or
  reliability risk, or a change whose parts must land in a specific order.

When uncertain, choose the full plan. Choose it for real risk, not merely because several
files change: a tightly coupled test and implementation update can still be
lightweight. If the brainstorm spans independent subsystems, split it into
separate plans that each produce independently testable software.

## Stacked pull-request planning

Plans must be implementable as a GitHub stacked pull-request chain without
rewriting history:

- Resolve and record the trunk/base branch and a stable stack slug. Use the
   repository default branch unless the user specifies another base.
- Keep a lightweight plan as one unit when it is genuinely contained. For
   standard and full plans, make every ordered task or commit one independently
   reviewable stack unit. Do not create artificial units just to produce more
   branches.
- For every stack unit, record its proposed branch name (for example,
   `<stack-slug>/01-<short-slug>`), parent branch, files, dependencies on earlier
   units, focused validation, and gate command. Units must be executable in
   bottom-to-top order without relying on uncommitted work from another unit.
- Full plans must order units from the base branch upward and state the exact
   output each unit provides to the next one. Standard plans must include the
   same parent and dependency information in each ordered task.
- The plan must say that implementation creates one or more linear commits per
   unit branch, with reviewer fixes remaining on that branch, and
   that `rs-implement-plan` opens the pull requests itself, as a stack or one PR,
   when its checkpoint asks for them. Planning does not push, create, merge, or rewrite
   pull requests.

## Step 2 — Agree the code structure

Once you understand the problem and see a solution, agree its shape with the user before
drafting. Start from any naming conventions the harness has saved to memory.

Show, in a plain message (a tree does not fit a question's options):

1. **The tree** -- every file the change touches, marked new, modified, or deleted, including
   new modules, folders, and test files.
2. **Contents** -- for each file, one or two lines on what it will hold (its main functions,
   classes, and constants) and the boundary it owns.
3. **Sample names** -- up to five real names the plan would create (all of them when it creates
   fewer), each with its kind and a one-line reason. Spread them across kinds (function, class,
   constant, variable, test) wherever the change has them.

Ask the user to approve or request changes. Revise and show the proposal again until the user
explicitly approves it. The step is done only on that approval; draft nothing before it.

Then state the naming rules the user's feedback implies (for example: verb-first function
names, no `_helper` suffix) and name every other function, class, variable, and file in the
plan by them. When the harness has a memory system, save the rules as a `feedback` memory,
updating an existing naming memory rather than adding a second one.

When the change creates no file and no new name, say so in one line and go on to Step 3.

## Step 3 — Write the draft plan

Open every plan, whatever its tier, by naming its tier and the brainstorm path it implements (or,
for issue or task input, the source set), so later commands never have to infer them. Every tier also carries an
**Approved structure and naming** section: the tree and naming rules agreed in Step 2.

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
5. **Approved structure and naming** -- the tree and naming rules agreed in Step 2.

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

Write the test plan (a standard plan's test notes) as the `unit-tests` skill's edge-case
catalogue: one row per rule, the test name that guards it, and its file.

## Step 4 — Review passes

For a **lightweight plan**, self-review it before reporting back: verify it covers
every settled decision, names the exact code path and validation, has no placeholder,
does not add unnecessary work, and matches the approved tree and naming rules. Do not make the three review passes unless new
information raises the plan to full scope.

For a **standard plan**, perform the same self-review, then make one focused
correctness review pass yourself. Read the actual source and tests and identify broken
callers, behavior regressions, error-path gaps, and missing validation. Incorporate
supported findings. Do not expand to three passes unless new information raises
the plan to full scope.

For a **full plan**, once the plan file exists, make three separate review passes yourself, each over the
brainstorm and the plan. In each, read the actual source files
rather than trusting the plan's claims about them.

- **Correctness pass.** Does each commit leave the
  repo importable, runnable, and its tests passing? Hunt for deletions whose callers
  survive, survivors whose dependencies are deleted, behaviour that silently changes,
  and error or state paths that quietly differ from today.
- **Domain and framework pass.** For the frameworks,
  libraries, and versions this repo actually has installed, is the proposed approach the
  current correct idiom? Check the API surfaces the plan calls, the version constraints,
   and any pattern the plan copies from a reference or template. Use Context7's
   `resolve-library-id` and `query-docs` when current library documentation is needed.
- **Devil's advocate pass.** Argue the plan is wrong. Attack the
  premises the brainstorm settled on, especially any decision justified by future work
  that is not yet scheduled. Attack every deletion by naming what breaks if the future
  never arrives. Name the cheaper plan that gets most of the benefit.

Each pass yields findings ranked by severity, each with a file path, a line, and a
concrete failure scenario. No style notes, no praise.

## Step 5 — Revise

For a full plan, revise it yourself with what the passes surfaced. Add an **Open
questions and rejected objections** section recording every finding, whether you
accepted it, and why. Do not make a fourth pass. For a lightweight plan, correct
any self-review finding inline and add only genuine unresolved questions. For a
standard plan, correct supported review findings inline and record only genuine
unresolved questions or rejected objections.

Stop before implementing. Ask the user to review and explicitly approve the written
plan before handing it to `$rs-implement-plan`.

Report back: the plan path, whether it was lightweight, standard, or full, the task
or commit count where applicable, and the findings you accepted.
