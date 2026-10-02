---
name: rs-implement-plan
description: "Implement a written plan with TDD at every tier and review proportional to its lightweight, standard, or full scope"
argument-hint: <plan-path>
agent: agent
tools: ["edit", "execute", "read", "search"]
---
> **Harness note.** This workflow was written for Claude Code, which can spawn
> named read-only subagents (`preflight-scout`, `commit-auditor`,
> `correctness-lens`, `framework-lens`, `guidance-compliance-lens`). Copilot has
> no equivalent. Wherever the steps below say to spawn one of those agents,
> perform that role yourself, in a separate pass over the diff, and report its
> findings under that agent's name. Every other rule — the ordering, the TDD
> rule, the gate-before-commit rule, the ledger — applies unchanged.

Plan: $1

You are the implementer and the only writer. Copilot cannot dispatch subagents, so every review role
is a separate pass of yours over a diff file, and you apply the fixes yourself.

Workspace: `docs/cc_logs/<plan-filename-stem>/` (gitignored; create it if missing). Files:

- `ledger.md` — resume map and run log. Trust it and `git log` over your own memory.
- `unit-<NN>.diff` — `git diff <BASE>..HEAD` for that unit, `BASE` being the unit branch's start.
- `branch.diff` — `git diff <base>...HEAD` for the final review.

If `ledger.md` already starts with this plan path, a line `Unit <NN>: complete` means that unit is
done; resume at the first unit without one.

---

## Step 1 — Pre-flight

Read the plan in full. Identify its stated tier: **lightweight**, **standard**, or **full**. If the
plan does not name one, infer the smallest safe tier from its actual scope. Escalate only when live
code exposes a concrete major, cross-component, interface, migration, or reliability risk; do not
add process merely because several related files change.

For a **lightweight plan**, verify the named files, current behavior, and focused validation command
yourself, then write a short status and staleness note to the ledger. One contained change needs no scout.

When implementation or review depends on current external framework or library
behavior, use Context7 before changing code: call `resolve-library-id` for the
exact library and installed version, then call `query-docs` with that identifier.
Record any material documentation result in the ledger. The checked-out code,
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

Write the scout's table and blockers into the ledger verbatim.

Also record in the ledger: the base branch (`gh repo view --json defaultBranchRef --jq
.defaultBranchRef.name` unless the user named another) and the stack slug; the staleness result from
`git fetch` then `git log --name-only <plan-base>..origin/<base>` (re-read a cited line only when that
log touches its file; an empty log is a clean result, not a skipped check); a conflict table with one
row per pair of units that share a file or public interface, naming what one produces and the other
consumes (rule on nothing; a contradiction that blocks implementation is a checkpoint question); and
the operator actions the plan needs before a live gate (API keys, credits, billed tiers, a running
database; an empty list is valid).

## Step 2 — The checkpoint

**Stop here.** This is the only scheduled stop in the run.

For a **lightweight plan**, show the direct pre-flight note and ask whether to proceed. For a
**standard or full plan**, show the scout's table and blockers, then ask which task or commit the
run should start from and whether to proceed. Also show the conflict table and operator checklist and ask whether the checklist is done: a live
gate whose key or credit is missing stays blocked, and you do not start a later unit to get around
it. Begin implementing only after the user answers. If
the user does not respond, the run does not start.

## Step 3 — Implementation

Walk the plan's ordered change steps, tasks, or commits **in order**, starting where the user said.
Work on one at a time, in the plan's order — the ordering is the plan's safety property.

You implement every unit directly. The standard plan receives exactly one final `correctness-lens`
pass. Before editing a unit's branch, record `BASE` (`git rev-parse HEAD`) in the ledger.

### Stacked pull-request compatibility

Keep every ordered plan unit independently reviewable and compatible with GitHub's `gh stack` workflow:

- At pre-flight, record the trunk/base branch and a stable stack slug. The default base is the repository's default branch from `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name` unless the user specifies another one.
- Each ordered plan unit must have its own linear branch. Create the unit branch from the previous branch before editing, use names such as `<stack-slug>/01-<short-slug>`, and keep the implementation and any reviewer-fix commits on that branch. Never squash, merge, reorder, or rewrite those commits.
- Record each unit branch, its parent branch, commits, focused validation, gate output, and ledger entry. Reviewers and auditors compare a unit branch with its immediate parent, not only with the cumulative top branch.
- Do not push or create pull requests in this command. The separate `rs-create-stacked-prs` workflow adopts the ordered branches with `gh stack init ... --base <base>`, previews them with `gh stack view`, and submits them with `gh stack submit --auto` or `--auto --open`.
- If existing work is not already split into linear unit branches, leave history unchanged and let `rs-create-stacked-prs` create cumulative branch pointers. Never force-push or silently rewrite history here.

### TDD rule

For every feature, bug fix, refactor, or other production behavior change in every plan tier, use
red-green-refactor:

1. Write one focused test for the behavior that is missing or must change.
2. Run it and confirm it fails for the expected reason, not due to a typo or broken setup.
3. Write the smallest production change that makes it pass.
4. Re-run the focused test and the plan's relevant gate. Refactor only while both remain green.

Write production behavior code only after its test fails. Documentation-only, configuration-only,
generated-code, and explicitly approved throwaway-prototype work are exceptions; record the exception
and the validation used in the ledger. A test that passes before the change does not establish the
needed behavior; revise it until it fails correctly.

For each unit of work:

1. Follow the TDD rule when the unit changes production behavior; otherwise make the change exactly
  as the plan specifies.
2. Run the plan's focused validation and gate command (`make test`, `make lint`, whatever the plan
  names).
3. **Commit only once the validation and gate are green.** A red gate is fixed before committing, never after. Fix
   forward applies to *reviewer findings only*, never to gate failures.
4. Append to the ledger: the commit subject, the gate command you ran, and the **tail of its real
   output**. This is the evidence that the gate actually ran; an entry without it is treated as a
   skipped gate.
5. For a standard plan, run Step 4 only when the scout marked the unit `moderate` or `high`. For a
   full plan, run Step 4 after every unit. A lightweight plan does not require a per-unit audit unless
   implementation reveals a concrete risk that escalates its tier.

## Step 4 — Per-unit audit

Write `unit-<NN>.diff` as `git diff <BASE>..HEAD`. Never use `HEAD~1`: a unit may have more than one
commit. Then, as the `commit-auditor`, read that diff, the plan section it implements, and the real
source files, and give three verdicts:

- **Spec** — `PASS` or `FAIL`, with file:line for anything the plan asked for that the diff does not
  do, or the diff does and the plan did not ask for. `HALT` when the plan section cannot be applied to
  the current code or the diff does something the plan never asked for; a `HALT` is also a `FAIL`.
- **Quality** — `PASS` or `FAIL`. `Important`: wrong behavior, a missed requirement, a test that cannot
  fail, an assertion on a fake, or an expected value computed by the code under test. `Minor`: polish.
- **Gate** — `PASS` only if the ledger entry holds a real gate command and output tail.

Then:

- **`HALT`** → stop the run, report it to the user, and wait. This is a scope question and it is not
  yours to settle.
- **`FAIL` or an `Important` finding** → fix it as a follow-up commit, using the TDD rule when behavior
  changes, then gate and log it. Re-audit only the fix diff, from the previous review's head. At most
  two fix rounds per unit; if it still fails, stop and ask the user.
- **`Minor`** → copy it into the ledger. It does not block the next unit.

Then append `Unit <NN>: complete (commits <BASE>..<head>, review <clean|N minor>)` to the ledger.

## Step 5 — Final review

After the last plan unit, review the result against the branch diff
(`git diff <base>...HEAD`, base being the commit the run started from) according to its tier:

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

Give each spawned lens the plan path, the diff path, and an instruction to **message its findings to
the lead** and to read the real source files. A standard plan receives only the first brief. If a
lens should use the repo's review tooling, say so in its spawn prompt — a `skills:` field in an agent
definition is ignored for teammates, so it cannot be preloaded.

Write `branch.diff` first and review that file. Fix substantive findings in one wave before
completing the run. For a behavior change, use the TDD rule; in all
cases rerun the focused validation and applicable gate. Then rerun the same lens on the fix diff. A
finding that contradicts the approved plan is a `HALT`; stop and ask the user rather than silently
expanding scope. Any other residual goes in the ledger and the Step 6 report; there is no second fix
wave.

## Step 6 — Report

Write any lens findings into the ledger, then **also print them to the terminal**. The ledger is
gitignored, so anything that exists only there is invisible to any later reader. For lightweight
plans, record the lead's final self-review instead.

Report to the user: the plan path and tier, tasks or commits made, units audited and what the audits
found, what was fix-forwarded, any `HALT` you hit, the outstanding applicable review findings you did
**not** act on, and the ledger path.

Stop at the last commit; `rs-create-stacked-prs` pushes and opens the pull requests.

---

## Standing rules

- Every spawned subagent (`scout`, `auditor`, implementer, and all three lenses) runs on Sonnet 5.5 at
  medium effort; no other model or effort level.
- You are the only writer; every review role is read-only, and you apply the fixes.
- Reviewers must be told to message their findings. An idle notification tells you a teammate
  stopped; it does not carry its output.
- Mark a commit done only on a gate you actually ran.
- Mark a behavior change done only once the failing focused test, green validation, and applicable
  gate are recorded.
- Where the plan and the code disagree, the code wins, and the disagreement goes in the ledger.
