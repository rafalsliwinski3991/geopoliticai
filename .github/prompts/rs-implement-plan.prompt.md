---
name: rs-implement-plan
description: "Implement one or more written plans with TDD and tiered review, then open each plan's sourced pull requests as a stack or one PR"
argument-hint: <plan-path>...
agent: agent
tools: ["context7/*", "edit", "execute", "read", "search"]
---

Input: the text the user typed after the command. Every path in it is a plan; run them all, in the
order given. Each plan is its own run: its own tier, ledger, pre-flight, stack of unit branches cut
from the base branch, final review, and pull requests. Steps 1 and 2 cover every plan up front; Steps
3–6 then run for one plan at a time, and the next plan starts from a fresh checkout of the base
branch. Step 7 reports on all of them.

You are the implementer and the only writer. Copilot cannot dispatch subagents, so every review role
is a separate pass of yours over a diff file, and you apply the fixes yourself. You also write the ledger, the diff files, and the pull-request bodies.

Workspace, one directory per plan: `docs/harness_logs/copilot/<plan-filename-stem>/` (gitignored; create it if missing). Files:

- `ledger.md` — resume map and run log. Trust it and `git log` over your own memory. It is exempt from `docs/harness_logs/TEMPLATE.md`: no header, no metrics table.
- `unit-<NN>.diff` — `git diff <BASE>..HEAD` for that unit, `BASE` being the unit branch's start.
- `branch.diff` — `git diff <base>...HEAD` for the final review.

If `ledger.md` already starts with this plan path, a line `Unit <NN>: complete` means that unit is
done; resume at the first unit without one. When every unit is complete and the ledger has a
`Final heads:` line but no `PR: <url>` line (a `PRs: none` line does not count), run Steps 1 and 2 as usual, then go straight to Step 6.

---

## Step 1 — Pre-flight

Run this step for every plan. Read the plan in full. Identify its stated tier: **lightweight**, **standard**, or **full**. If the
plan does not name one, infer the smallest safe tier from its actual scope. Escalate only when live
code exposes a concrete major, cross-component, interface, migration, or reliability risk; do not
add process merely because several related files change.

For a **lightweight plan**, verify the named files, current behavior, and focused validation command
yourself, then write a short status and staleness note to the ledger. One contained change needs no separate pre-flight pass.

When implementation or review depends on current external framework or library
behavior, use Context7 before changing code: call `resolve-library-id` for the
exact library and installed version, then call `query-docs` with that identifier.
Record any material documentation result in the ledger. The checked-out code,
lockfile, and repository guidance remain authoritative for local behavior.

For a **standard or full plan**, make a separate pre-flight pass yourself over the plan, using this brief:

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
> the current code. Write nothing to disk and change nothing. Write the table and the blockers
> into the ledger.

Write the pass's table and blockers into the ledger verbatim.

Also record in the ledger: the base branch (`gh repo view --json defaultBranchRef --jq
.defaultBranchRef.name` unless the user named another) and the stack slug; the staleness result from
`git fetch` then `git log --name-only <plan-base>..origin/<base>`, where `<plan-base>` is `git rev-list -1 --before="$(date -r <plan-path> -Iseconds)" origin/<base>`, the base branch as it stood when the plan file was last written (re-read a cited line only when that
log touches its file; an empty log is a clean result, not a skipped check); a conflict table with one
row per pair of units that share a file or public interface, naming what one produces and the other
consumes (rule on nothing; a contradiction that blocks implementation is a checkpoint question); and
the operator actions the plan needs before a live gate (API keys, credits, billed tiers, a running
database; an empty list is valid).

Then map every plan unit to its **sources**: the Asana tasks, GitHub issues, and Aikido issues it
delivers. Take them from the unit itself (plans made by `rs-plan-from-asana` and
`rs-plan-from-gh-issues` name them per unit); a unit that names none inherits the sources in the
plan's Scope. Record the map in the ledger. A unit left with no source is a checkpoint question.

## Step 2 — The checkpoint

**Stop here.** This is the only scheduled stop in the run.

Present every plan in one checkpoint. For a **lightweight plan**, show the direct pre-flight note. For a
**standard or full plan**, show the pass's table and blockers, then ask which task or commit its
run should start from. Ask once, for all plans, whether to proceed. Show the unit-to-source map and ask for the source of
any unit that has none. Also show the conflict table and operator checklist and ask whether the
checklist is done: a live gate whose key or credit is missing stays blocked, and you do not start a
later unit to get around it.

Ask how Step 6 opens the pull requests:
- **a stack**, one PR per unit, or **one PR** for the whole plan;
- or **none**, leaving the branches local and unpushed;
- and **draft** or **ready for review**.

Begin implementing only after the user answers. If the user does not respond, the run does not start.

## Step 3 — Implementation

Walk the plan's ordered change steps, tasks, or commits **in order**, starting where the user said.
Work on one at a time, in the plan's order — the ordering is the plan's safety property.

You implement every unit directly. The standard plan receives exactly one final `correctness-lens`
pass. Before editing a unit's branch, record `BASE` (`git rev-parse HEAD`) in the ledger.

### Stacked pull-request compatibility

Keep every ordered plan unit independently reviewable and compatible with GitHub's `gh stack` workflow:

- Each plan gets its own stack slug and its own chain, whose bottom branch is cut from the base branch. Plans never stack on one another.
- At pre-flight, record the trunk/base branch and a stable stack slug. The default base is the repository's default branch from `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name` unless the user specifies another one.
- Each ordered plan unit must have its own linear branch. Create the unit branch from the previous branch before editing, use names such as `<stack-slug>/01-<short-slug>`, and keep the implementation and any reviewer-fix commits on that branch. Never squash, merge, reorder, or rewrite those commits.
- Record each unit branch, its parent branch, commits, focused validation, gate output, and ledger entry. Review passes compare a unit branch with its immediate parent, not only with the cumulative top branch.
- If existing work is not already split into linear unit branches, leave history unchanged and stop that plan at Step 6: report that its history needs one branch per unit. Cut each as `git branch <stack-slug>/NN-<short-slug> <sha>` at the unit's last commit (check each SHA against `git ls-remote origin`, and that each branch descends from the one below it, so the chain stays linear), then rerun; or open its pull requests by hand with `gh pr create --base <parent>`. Never force-push or silently rewrite history here.

### TDD rule

For every feature, bug fix, refactor, or other production behavior change in every plan tier, use
red-green-refactor:

1. Write one focused test for the behavior that is missing or must change, by the `unit-tests`
   skill.
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
5. For a standard plan, run Step 4 only when the pre-flight pass marked the unit `moderate` or `high`. For a
   full plan, run Step 4 after every unit. A lightweight plan does not require a per-unit audit unless
   implementation reveals a concrete risk that escalates its tier.

## Step 4 — Per-unit audit

Write `unit-<NN>.diff` as `git diff <BASE>..HEAD`. Never use `HEAD~1`: a unit may have more than one
commit. Then, in a separate review pass, read that diff, the plan section it implements, and the real
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
  changes, then gate and log it. After each fix, rewrite `unit-<NN>.diff` from `BASE` to the new HEAD and re-audit that whole unit diff. At most
  two fix rounds per unit; if it still fails, stop and ask the user.
- **`Minor`** → copy it into the ledger. It does not block the next unit.

Then append `Unit <NN>: complete (commits <BASE>..<head>, review <clean|N minor>)` to the ledger.

## Step 5 — Final review

After the last plan unit, review the result against the branch diff
(`git diff <base>...HEAD`, base being the plan's base branch) according to its tier:

- **Lightweight plan** -- review the final diff yourself against its scope and focused validation.
  Make a lens pass only when a concrete finding escalates the work.
- **Standard plan** -- make exactly one `correctness-lens` pass, using the correctness brief below.
- **Full plan** -- make all three lens passes, one after another, each as a separate review pass you
  make yourself over `branch.diff`.

- `correctness-lens` — broken call sites, deletions whose callers survive, behaviour that silently
  changed, error and state paths that differ from before.
- `framework-lens` — is this the current correct idiom for the versions **actually installed** in
  this repo? Check the API surfaces the diff calls and the version constraints it assumes.
  Use Context7's `resolve-library-id` and `query-docs` when current external
  documentation is needed.
- `guidance-compliance-lens` — did this change require updating `CLAUDE.md`, `AGENTS.md`, and
  `.github/copilot-instructions.md` per this repo's own rule, and do those files still describe the
  code truthfully?

In each pass, work from the plan path and the diff path, and read the real source files. A standard
plan makes only the first pass.

Write `branch.diff` first and review that file. Fix substantive findings in one wave before
completing the run. For a behavior change, use the TDD rule; in all
cases rerun the focused validation and applicable gate. Then rerun the same lens pass on the fix diff. A
finding that contradicts the approved plan is a `HALT`; stop and ask the user rather than silently
expanding scope. Any other residual failure or substantive finding stops the run the same way: show it
and ask the user before Step 6. Only minor residuals go in the ledger and the Step 7 report; there is no
second fix wave.

Then append `Final heads: <unit-01-branch> <sha>, …, <top-branch> <sha>` to the ledger, from
`git rev-parse refs/heads/<branch>` for every unit branch. Step 6 checks the branches against this line.

## Step 6 — Pull requests

Once the plan's final review is clean, open its pull requests in the shape the checkpoint chose. The
checkpoint answer is the authorization; ask again only when something below stops the step. A live or
smoke gate that is still failing or open does not stop this step: list it under "Checks" in every
description it concerns. If the answer was **none**, append `PRs: none (checkpoint)` to the ledger and go
to Step 7. A later run on the same plan resumes here (see the resume rule above) and asks again at its
checkpoint.

1. Confirm `gh auth status` succeeds. For a stack, also confirm `gh stack --help` is available; if the
   extension is missing, stop and report `gh extension install github/gh-stack`; never install it.
2. Confirm the working tree is clean, and that every unit branch is at the SHA on the ledger's
   `Final heads:` line. Confirm the history is linear: `git merge-base --is-ancestor <base>
   <unit-01-branch>` succeeds, and `git rev-list --merges <base>..<top-branch>` prints nothing. For each
   branch, check `git ls-remote --exit-code origin refs/heads/<branch>`. If the remote branch exists at a
   SHA other than the local branch's, stop and report it; never force-update an existing branch.
3. Open the pull requests:
   - **A stack.** Check out the top branch and run `gh stack view`. If it already lists the plan's unit
     branches in order, skip init. Otherwise adopt them, bottom to top, without touching their commits:
     `gh stack init --base <base> <unit-01-branch> ... <top-branch>`, which leaves the top branch
     checked out. Then run `gh stack view`. Every branch must have its intended parent; if one does
     not, stop and report rather than submit. Submit with `gh stack submit --auto` for drafts, or
     `gh stack submit --auto --open` for ready for review. On a rerun whose PRs already exist, the same
     command updates them. If an existing PR's base is not the layer below, stop and ask the user
     rather than repair it.
   - **One PR.** Push the top branch with `git push -u origin <top-branch>`. If a PR already heads it
     (`gh pr list --head <top-branch> --json number`), reuse that PR. Otherwise write its description
     first (item 4), then run `gh pr create --base <base> --head <top-branch> --title "<plan title>" --body-file <file>`, adding
     `--draft` for a draft. The title is the plan's own title line without its leading `# Plan:`.
4. Load the `writing-for-people` skill. Then write each description to a file in the scratchpad and
   apply it with `gh pr edit <number> --body-file <file>`; on a rerun this replaces the existing
   description. Take every section from the plan, the ledger,
   and the diff (`unit-<NN>.diff`, or `git diff <parent>..<branch>`), and never invent one. A section with
   nothing to report is one line, such as "Audit clean.". Use these headings, in this order:

   ```markdown
   ## What this PR does
   <two to four plain sentences: what a user or developer sees change>

   ## Why
   <the plan path and section, such as `docs/plans/<file>.md` §4.4, and the reason in one or two sentences>

   ## Why this PR exists
   <"Plan unit <NN>." Then each commit added to the unit during the run, as `<sha> <subject>`, with the
   failed check or finding that caused it, taken from the ledger>

   ## How to review it
   1. `<path>`: <what to check there>
   <one line per file, in the order a reviewer should read them: riskiest first, tests last>

   ## What implement-plan's own review found
   <the unit's audit verdicts and every Minor the ledger kept, or "Audit clean."; the final-review lens
   findings on this unit's files and what was done with each>

   ## Checks
   <the focused validation and gate commands with their result; every live or smoke gate that failed or
   is still open, from the ledger; or "All gates green.">

   ## Source

   - Asana: <task URL>
   - GitHub: Closes #<n>
   - GitHub: Refs #<n>
   - Aikido: <issue id> <issue link>
   ```

   **A stack** gets one description per layer, built from that unit.

   **One PR** gets one description for the whole plan:
   - "Why this PR exists" says `Plan units 01–<NN> in one PR (checkpoint choice).`, followed by the
     commits each unit added during the run.
   - "How to review it" and "What implement-plan's own review found" are grouped by unit, in plan order.
   - `## Source` lists every unit's sources, with every delivered issue as `Closes`.

   In a stack, a GitHub issue is `Closes` on the last unit that delivers it and `Refs` on every earlier
   one. A unit the user confirmed at the checkpoint has no source gets the single line
   `- None (confirmed at checkpoint)`, which `rs-gh-stack-merge` lists as manual.

   `rs-gh-stack-merge` parses the `## Source` lines to close the sources, so keep the heading and the
   prefixes verbatim. End the body with the pull-request attribution line the harness supplies, if it
   supplies one.
5. Record in the ledger one `PR: <url> <sources>` line per pull request, then show each line, plus the
   final `gh stack view` for a stack.

The step is done when every pull request has a body carrying every heading above and a non-empty
`## Source` section. Never merge a PR, force-push, or rewrite commits here; `rs-gh-stack-merge` merges
a stack.

## Step 7 — Report

Write any lens findings into the ledger, then **also print them to the terminal**. The ledger is
gitignored, so anything that exists only there is invisible to any later reader. For lightweight
plans, record the lead's final self-review instead.

Report on every plan. For each, report to the user: the plan path and tier, tasks or commits made, units audited and what the audits
found, what was fix-forwarded, any `HALT` you hit, the outstanding applicable review findings you did
**not** act on, the PR URLs with their sources (or "no PRs opened; rerun this command to open them"), and the ledger path.


---

## Standing rules

- You are the only writer; every review pass is read-only, and you apply the fixes.
- Mark a commit done only on a gate you actually ran.
- Mark a behavior change done only once the failing focused test, green validation, and applicable
  gate are recorded.
- Where the plan and the code disagree, the code wins, and the disagreement goes in the ledger.
