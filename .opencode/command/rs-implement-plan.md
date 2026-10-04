---
description: Implement one or more written plans with TDD, then open their pull requests as a stack or one PR, using OpenCode subagents
agent: build
model: opencode-go/glm-5.3-flash
---

Plans: $ARGUMENTS

You are the lead. You coordinate. You write briefs, the ledger, diff files, and pull-request bodies. You do not edit production code or tests. The subagents do that.

OpenCode dispatches a subagent with the Task tool. Set `subagent_type` to one of the names below. The Task tool has no model argument; the agent file pins the model. A dispatch that returns `Unknown agent type` means OpenCode has not loaded `.opencode/agents/` yet: stop and tell the user to quit and restart OpenCode. Do not implement the unit yourself.

| Role | `subagent_type` | Model |
|---|---|---|
| Implement one unit | `plan-implementer` | `opencode-go/glm-5.3-flash` |
| Second attempt after `BLOCKED` | `plan-retry` | `opencode-go/glm-5.3-flash` |
| Review one unit | `plan-unit-auditor` | `opencode-go/glm-5.3-flash` |
| Review the finished branch | `plan-final-review` | `opencode-go/deepseek-v4.1-flash` |

Do not dispatch `general`, `explore`, `preflight-scout`, `commit-auditor`, or a lens name. Those are not this command's workers.

Every argument is a plan path. Run them in the order given. Each plan has its own ledger, unit branches, and pull requests. Steps 1 and 2 cover every plan, then Steps 3–6 run one plan at a time. The next plan starts from a fresh checkout of the base branch.

Workspace, one directory per plan: `docs/harness_logs/<plan-filename-stem>/`. It is gitignored. Create it if missing. Files:

- `ledger.md` — resume map. Trust it and `git log` over your own memory. It is exempt from `docs/harness_logs/TEMPLATE.md`: no header, no metrics table.
- `unit-<NN>-brief.md` — that unit only.
- `unit-<NN>-report.md` — the implementer's report.
- `unit-<NN>.diff` — `git diff <base>..<head>` for that unit.
- `branch.diff` — `git diff <base>...HEAD` for the final review.
- `final-fix-brief.md`, `final-fix-report.md` — the final review's findings and the fix implementer's report.

If `ledger.md` already starts with this plan path, a line `Unit <NN>: complete` means that unit is done. Resume at the first unit without that line. When every unit is complete and the ledger has a `Final heads:` line but no `PR: <url>` line (a `PRs: none` line does not count), run Steps 1 and 2, then go straight to Step 5.

---

## Step 1 — Pre-flight

Do this yourself, for every plan. Done when `ledger.md` exists and contains the staleness result, the conflict table, the source map, the operator checklist, the base branch, and the stack slug.

Read the plan. Record its tier: **lightweight**, **standard**, or **full**. If it names none, pick the smallest tier that fits. Escalate only for a concrete cross-component, interface, migration, or reliability risk.

Resolve the base branch with `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`, unless the user named another. Record a stable stack slug. The plan's slug wins when it names one.

Run `git fetch`. Then `git log --name-only <plan-base>..origin/<base>`, where `<plan-base>` is `git rev-list -1 --before="$(date -r <plan-path> -Iseconds)" origin/<base>`, the base branch as it stood when the plan file was last written. Re-read a cited line only when that log touches the file. Write the result in the ledger. An empty log is a clean staleness result, not a skipped check.

Write a conflict table: one row per pair of units that share a file or a public interface, naming what one produces and the other consumes. One row per unit whose tests and code disagree inside the plan. Rule on nothing. This table is for you; a contradiction that blocks implementation is a checkpoint question.

List operator actions the plan requires before a live gate: API keys, credits, billed tiers, a running database. An empty list is valid.

Map every unit to its Asana tasks, GitHub issues, and Aikido issues. A unit that names none inherits the plan's Scope sources. A unit with no source is a checkpoint question.

## Step 2 — The checkpoint

Stop. This is the only scheduled stop. Use the `question` tool. If that tool is unavailable, ask in text and wait. Do not start on silence.

Show, for every plan: tier, staleness, conflict table, source gaps, and the operator checklist. Ask which unit to start from, how Step 5 opens the pull requests (**a stack**, one PR per unit, **one PR** for the whole plan, or **none**, leaving the branches local; and **draft** or **ready for review**), and whether the checklist is done. Begin Step 3 only after the user answers.

A live gate whose key or credit is missing stays blocked. Do not start the next unit to get around it.

## Step 3 — One unit at a time

Walk units in plan order, starting where the user said. Finish the unit's audit before cutting the next branch. The parent branch must contain the unit's commits before the child branch is created.

For each unit:

1. Create `<stack-slug>/<NN>-<short-slug>` from the previous unit's branch. Unit 01's parent is the base branch. Check it out. Record `BASE` with `git rev-parse HEAD` in the ledger.
2. Write `unit-<NN>-brief.md`. Copy that unit's plan section, the interfaces earlier units established, the branch name, `BASE`, the focused test command, and the full gate command. Do not copy the rest of the plan.
3. Dispatch `plan-implementer`. The task prompt is the brief path, the report path, and one line on where the unit sits. Do not paste the plan.
4. Read the status:
   - `DONE` or `DONE_WITH_CONCERNS`: go to the audit.
   - `NEEDS_CONTEXT`: add the missing fact to the brief and dispatch `plan-implementer` again.
   - `BLOCKED`: dispatch `plan-retry` once, with the brief path, the report path, and the failure. If that attempt is also `BLOCKED`, stop and ask the user.
5. Write `unit-<NN>.diff` from `BASE` to the unit's HEAD. Never use `HEAD~1`; a unit may have more than one commit.
6. Dispatch `plan-unit-auditor` with the brief path, the report path, and the diff path.
7. Apply the audit result:
   - `HALT`: stop the run, show the finding, and wait.
   - `FAIL` or an `Important` finding: dispatch `plan-implementer` with the findings, at most twice. After each fix, rewrite `unit-<NN>.diff` from `BASE` to the new HEAD and dispatch `plan-unit-auditor` on that whole unit diff. If the unit still fails after the second fix, stop and ask the user; do not mark it complete.
   - `Minor`: copy it into the ledger. It does not block the next unit.
   - Gate `FAIL`: the implementer re-runs the gate and appends the tail before you mark the unit complete.
8. Append `Unit <NN>: complete (commits <base>..<head>, review <clean|N minor>)`.

A commit is done only when the report shows a green focused run and a green full gate. You do not weaken a gate the plan names.

## Step 4 — Final review

After the last unit, write `branch.diff` for `git diff <base>...HEAD`.

- **Lightweight:** read that diff yourself against the plan's scope. Dispatch `plan-final-review` only if you find a concrete risk.
- **Standard or full:** dispatch `plan-final-review` once, with the plan path, `branch.diff`, and the ledger.

If it returns findings, write `final-fix-brief.md`: the full findings list, the plan path, the branch, `BASE` (the current HEAD), the focused test commands, and the full gate command. Dispatch one `plan-implementer` with that brief and the report path `final-fix-report.md`. Then rewrite `branch.diff` and dispatch one `plan-unit-auditor` with `final-fix-brief.md`, `final-fix-report.md`, and `branch.diff`. A residual that contradicts the plan is `HALT`. A residual `FAIL` or `Important` finding also stops the run: show it and ask the user before Step 5. Only `Minor` residuals go in the ledger and in the Step 6 report. There is no second fix wave.

Then append `Final heads: <unit-01-branch> <sha>, …, <top-branch> <sha>` to the ledger, from
`git rev-parse refs/heads/<branch>` for every unit branch. Step 5 checks the branches against this line.

## Step 5 — Pull requests

Once the final review is clean, open its pull requests in the shape the checkpoint chose. The
checkpoint answer is the authorization; ask again only when something below stops the step. A live or
smoke gate that is still failing or open does not stop this step: list it under "Checks" in every
description it concerns. If the answer was **none**, append `PRs: none (checkpoint)` to the ledger and go
to Step 6. A later run on the same plan resumes here (see the resume rule above) and asks again at its
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

## Step 6 — Report

Print, per plan: path, tier, units completed, audit results, any `HALT`, residual findings, PR URLs (or "no PRs opened; rerun this command to open them"), and the ledger path. The ledger is gitignored, so this report is the copy a later reader can see.

---

## Standing rules

- One implementer at a time, on the checked-out unit branch. A later unit's branch does not exist until the earlier unit has committed.
- The brief file is the unit's requirements. The task prompt points at it.
- Where the plan and the code disagree, the code wins. Record the disagreement. If the unit then cannot be implemented as written, `HALT` and ask.
- Reviewer agents have `edit: deny`. If you ask one to change a file, the tool will fail.
