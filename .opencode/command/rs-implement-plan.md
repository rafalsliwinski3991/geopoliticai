---
description: Implement one or more written plans with TDD and tiered review, then open one sourced stacked PR chain per plan
agent: build
model: opencode-go/glm-5.3-flash
---
> **Harness note.** This workflow was written for Claude Code, which can spawn named read-only
> subagents (`preflight-scout`, `commit-auditor`, `correctness-lens`, `framework-lens`,
> `guidance-compliance-lens`). OpenCode has a subagent mechanism but none of those agents, so a
> literal dispatch errors on an unknown name. Wherever the steps below say to spawn one, perform
> that role yourself, in a separate pass, and report its findings under that agent's name. Every
> other rule applies unchanged.

Plans: $ARGUMENTS

Every argument is a plan path; run them all, in the order given. Each plan is its own run: its own
tier, run log, pre-flight, stack of unit branches cut from the base branch, final review, and
stacked PR chain. Steps 1 and 2 cover every plan up front; Steps 3–6 then run for one plan at a time,
and the next plan starts from a fresh checkout of the base branch. Step 7 reports on all of them.

You are the **implementer** and the team lead. For lightweight and standard plans, you are the only
writer in this run. For a full plan, you may delegate one genuinely independent task at a time to a
fresh implementer agent; otherwise you remain the writer. Every review agent is read-only and exists
to check the work.

Run log, one per plan: `docs/cc_logs/<plan-filename-stem>_run.md` (create `docs/cc_logs/` if missing; it is
gitignored). If that file already exists, append a new dated section rather than overwriting it.

---

## Step 1 — Pre-flight

Run this step for every plan. Read the plan in full. Identify its stated tier: **lightweight**, **standard**, or **full**. If the
plan does not name one, infer the smallest safe tier from its actual scope. Escalate only when live
code exposes a concrete major, cross-component, interface, migration, or reliability risk; do not
add process merely because several related files change.

For a **lightweight plan**, verify the named files, current behavior, and focused validation command
yourself, then write a short status and staleness note to the run log. One contained change needs no scout.

When implementation or review depends on current external framework or library
behavior, use Context7 before changing code: call `resolve-library-id` for the
exact library and installed version, then call `query-docs` with that identifier.
Record any material documentation result in the run log. The checked-out code,
lockfile, and repository guidance remain authoritative for local behavior.

For a **standard or full plan**, spawn a single teammate named `scout` using the `preflight-scout` agent
type, and give it the plan path and this brief:

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
>   plan assumes, whether `main` has advanced since the plan was written, or `—` if clean.
>
> Below the table, list any **blockers**: plan sections that cannot be implemented as written against
> the current code. Write nothing to disk and change nothing. Return the table and the blockers as
> your message to the lead — an idle notification carries no output, so you must send it explicitly.

Write the scout's table and blockers into the run log verbatim.

Then map every plan unit to its **sources**: the Asana tasks, GitHub issues, and Aikido issues it
delivers. Take them from the unit itself (plans made by `rs-plan-from-asana` and
`rs-plan-from-gh-issues` name them per unit); a unit that names none inherits the sources in the
plan's Scope. Record the map in the run log. A unit left with no source is a checkpoint question.

## Step 2 — The checkpoint

**Stop here.** This is the only scheduled stop in the run.

Present every plan in one checkpoint. For a **lightweight plan**, show the direct pre-flight note;
for a **standard or full plan**, show the scout's table and blockers and ask which task or commit
its run should start from. For every plan, show the unit-to-source map and ask for the source of
any unit that has none. Then ask once, for all plans, whether to proceed and whether the stacked
PRs of Step 6 open as **drafts** or **ready for review**. Begin implementing only after the user
answers. If the user does not respond, the run does not start.

## Step 3 — Implementation

Walk the plan's ordered change steps, tasks, or commits **in order**, starting where the user said.
Work on one at a time, in the plan's order — the ordering is the plan's safety property.

Lightweight and standard plans are implemented directly by the lead. The standard plan receives exactly
one final `correctness-lens` review. For a full plan, delegate a unit only when it has no unresolved
dependency on another unfinished unit; give the fresh implementer only that unit's requirements,
relevant established interfaces, and the run-log contract. It must use this command's TDD rule, run
the planned validation, commit only while green, and report its evidence to the lead. Delegate one implementation unit at a time.

### Stacked pull-request compatibility

Keep every ordered plan unit independently reviewable and compatible with GitHub's `gh stack` workflow:

- At pre-flight, record the trunk/base branch and a stable stack slug. The default base is the repository's default branch from `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name` unless the user specifies another one.
- Each ordered plan unit must have its own linear branch. Create the unit branch from the previous branch before editing, use names such as `<stack-slug>/01-<short-slug>`, and keep the implementation and any reviewer-fix commits on that branch. Never squash, merge, reorder, or rewrite those commits.
- Record each unit branch, its parent branch, commits, focused validation, gate output, and run-log entry. Reviewers and auditors compare a unit branch with its immediate parent, not only with the cumulative top branch.
- Each plan gets its own stack slug and its own chain, whose bottom branch is cut from the base branch. Plans never stack on one another.
- If existing work is not already split into linear unit branches, leave history unchanged and stop that plan at Step 6: report that `rs-create-stacked-prs` must build its chain from cumulative branch pointers. Never force-push or silently rewrite history here.

### TDD rule

For every feature, bug fix, refactor, or other production behavior change in every plan tier, use
red-green-refactor:

1. Write one focused test for the behavior that is missing or must change.
2. Run it and confirm it fails for the expected reason, not due to a typo or broken setup.
3. Write the smallest production change that makes it pass.
4. Re-run the focused test and the plan's relevant gate. Refactor only while both remain green.

Write production behavior code only after its test fails. Documentation-only, configuration-only,
generated-code, and explicitly approved throwaway-prototype work are exceptions; record the exception
and the validation used in the run log. A test that passes before the change does not establish the
needed behavior; revise it until it fails correctly.

For each unit of work:

1. Follow the TDD rule when the unit changes production behavior; otherwise make the change exactly
  as the plan specifies.
2. Run the plan's focused validation and gate command (`make test`, `make lint`, whatever the plan
  names).
3. **Commit only once the validation and gate are green.** A red gate is fixed before committing, never after. Fix
   forward applies to *reviewer findings only*, never to gate failures.
4. Append to the run log: the commit subject, the gate command you ran, and the **tail of its real
   output**. This is the evidence that the gate actually ran; a run log entry without it is treated
   as a skipped gate.
5. For a standard plan, run Step 4 only when the scout marked the unit `moderate` or `high`. For a
   full plan, run Step 4 after every unit. A lightweight plan does not require a per-unit audit unless
   implementation reveals a concrete risk that escalates its tier.

## Step 4 — Per-unit audit

Spawn a teammate named `auditor` using the `commit-auditor` agent type, with this brief:

> Read `git diff HEAD~1` and the plan section at `<path>` that this commit implements. Report:
> (a) anything the plan asked for that the diff does not do; (b) anything the diff does that the plan
> did not ask for; (c) whether the run log entry for this commit records a real gate command and its
> output. Read the source files themselves rather than trusting either the plan or the diff summary.
> Rank findings by severity, each with a file path, a line, and a concrete failure scenario. No style
> notes, no praise. Message your findings to the lead directly.
>
> One finding type is **halt-severity**: a plan contradiction — the diff does something the plan never
> asked for, or the plan section is unimplementable as written against the current code. Mark those
> `HALT`. Everything else is ordinary.

Reuse the same auditor across units by messaging it rather than spawning a new one each time.

Then:

- **Ordinary findings** → fix them yourself as a follow-up commit, using the TDD rule when behavior
  changes, then gate and log it like any other. Re-run the same auditor against the fix diff before
  moving on. Record in the run log what was found and what you did.
- **A `HALT` finding** → stop the run, report it to the user, and wait. This is a scope question and
  it is not yours to settle.

## Step 5 — Final review

After the last plan unit, review the result against the branch diff
(`git diff <base>...HEAD`, base being the plan's base branch) according to its tier:

- **Lightweight plan** -- review the final diff yourself against its scope and focused validation.
  Spawn a lens only when a concrete finding escalates the work.
- **Standard plan** -- spawn exactly one `correctness-lens` using the correctness brief below.
- **Full plan** -- **you** spawn all three lenses in parallel. A teammate cannot spawn teammates, so
  this fan-out has to come from here.

- `correctness-lens` — broken call sites, deletions whose callers survive, behaviour that silently
  changed, error and state paths that differ from before.
- `framework-lens` — is this the current correct idiom for the versions **actually installed** in
  this repo? Check the API surfaces the diff calls and the version constraints it assumes.
  Use Context7's `resolve-library-id` and `query-docs` when current external
  documentation is needed.
- `guidance-compliance-lens` — did this change require updating `CLAUDE.md`, `AGENTS.md`, and
  `.github/copilot-instructions.md` per this repo's own rule, and do those files still describe the
  code truthfully?

Give each spawned lens the plan path, the diff range, and an instruction to **message its findings to
the lead** and to read the real source files. A standard plan receives only the first brief. If a
lens should use the repo's review tooling, say so in its spawn prompt — a `skills:` field in an agent
definition is ignored for teammates, so it cannot be preloaded.

Fix substantive findings before completing the run. For a behavior change, use the TDD rule; in all
cases rerun the focused validation and applicable gate. Then rerun the same lens on the fix diff. A
finding that contradicts the approved plan is a `HALT`; stop and ask the user rather than silently
expanding scope.

## Step 6 — Stacked pull requests

Once the plan's final review is clean, open its chain. The user's checkpoint answer is the
authorization; ask again only when something below stops the step.

1. Confirm `gh auth status` succeeds and `gh stack --help` is available. If the extension is
   missing, stop and report `gh extension install github/gh-stack`; never install it.
2. Adopt the plan's unit branches, bottom to top, without touching their commits:
   `gh stack init --base <base> <unit-01-branch> ... <top-branch>`, then `gh stack view`. Every
   branch must have its intended parent; if one does not, stop and report rather than submit.
3. Submit with `gh stack submit --auto` for drafts, or `gh stack submit --auto --open` for ready
   for review, as the checkpoint decided.
4. Rewrite every layer's description with `gh pr edit <branch> --body-file <file>` (write the file
   in the scratchpad). The body is a short summary of the unit from the plan, then a `## Source`
   section listing every source mapped to that unit, one per line, in exactly this form:

   ```text
   ## Source

   - Asana: <task URL>
   - GitHub: Closes #<n>
   - GitHub: Refs #<n>
   - Aikido: <issue id> <issue link>
   ```

   A GitHub issue is `Closes` on the last unit that delivers it and `Refs` on every earlier one.
   `rs-gh-stack-merge` parses these lines to close the sources, so keep the prefixes verbatim.
   End the body with the repository's pull-request attribution line.
5. Record in the run log, and show, every PR URL with its sources and the final `gh stack view`.

The step is done when every layer has a PR whose body carries a non-empty `## Source` section. Never
merge a PR, force-push, or rewrite commits here; `rs-gh-stack-merge` merges the chain.

## Step 7 — Report

Write any lens findings into each plan's run log, then **also print them to the terminal**. The run
log is gitignored, so anything that exists only there is invisible to any later reader. For
lightweight plans, record the lead's final self-review instead.

Report to the user, per plan: the plan path and tier, tasks or commits made, units audited and what
the audits found, what was fix-forwarded, any `HALT` you hit, the outstanding applicable review
findings you did **not** act on, the PR URLs with their sources, and the run log path.

---

## Standing rules

- Every spawned subagent (`scout`, `auditor`, implementer, and all three lenses) runs on Sonnet 5 at
  medium effort; no other model or effort level.
- You are the only writer. If you catch yourself asking a review agent to change something, stop —
  they have no write tools and the request will fail.
- Reviewers must be told to message their findings. An idle notification tells you a teammate
  stopped; it does not carry its output.
- Mark a commit done only on a gate you actually ran.
- Mark a behavior change done only once the failing focused test, green validation, and applicable
  gate are recorded.
- Where the plan and the code disagree, the code wins, and the disagreement goes in the run log.
