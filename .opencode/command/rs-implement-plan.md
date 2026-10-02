---
description: Implement one or more written plans with TDD and a stacked PR chain, using OpenCode subagents
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
| Review one unit | `plan-auditor` | `opencode-go/glm-5.3-flash` |
| Review the finished branch | `plan-final-review` | `opencode-go/deepseek-v4.1-flash` |

Do not dispatch `general`, `explore`, `preflight-scout`, `commit-auditor`, or a lens name. Those are not this command's workers.

Every argument is a plan path. Run them in the order given. Each plan has its own ledger, stack, and pull-request chain. Steps 1 and 2 cover every plan, then Steps 3–6 run one plan at a time. The next plan starts from a fresh checkout of the base branch.

Workspace, one directory per plan: `docs/cc_logs/<plan-filename-stem>/`. It is gitignored. Create it if missing. Files:

- `ledger.md` — resume map. Trust it and `git log` over your own memory.
- `unit-<NN>-brief.md` — that unit only.
- `unit-<NN>-report.md` — the implementer's report.
- `unit-<NN>.diff` — `git diff <base>..<head>` for that unit.
- `branch.diff` — `git diff <base>...HEAD` for the final review.

If `ledger.md` already starts with this plan path, a line `Unit <NN>: complete` means that unit is done. Resume at the first unit without that line.

---

## Step 1 — Pre-flight

Do this yourself, for every plan. Done when `ledger.md` exists and contains the staleness result, the conflict table, the source map, the operator checklist, the base branch, and the stack slug.

Read the plan. Record its tier: **lightweight**, **standard**, or **full**. If it names none, pick the smallest tier that fits. Escalate only for a concrete cross-component, interface, migration, or reliability risk.

Resolve the base branch with `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`, unless the user named another. Record a stable stack slug. The plan's slug wins when it names one.

Run `git fetch`. Then `git log --name-only <plan-base>..origin/<base>`. Re-read a cited line only when that log touches the file. Write the result in the ledger. An empty log is a clean staleness result, not a skipped check.

Write a conflict table: one row per pair of units that share a file or a public interface, naming what one produces and the other consumes. One row per unit whose tests and code disagree inside the plan. Rule on nothing. This table is for you; a contradiction that blocks implementation is a checkpoint question.

List operator actions the plan requires before a live gate: API keys, credits, billed tiers, a running database. An empty list is valid.

Map every unit to its Asana tasks, GitHub issues, and Aikido issues. A unit that names none inherits the plan's Scope sources. A unit with no source is a checkpoint question.

## Step 2 — The checkpoint

Stop. This is the only scheduled stop. Use the `question` tool. If that tool is unavailable, ask in text and wait. Do not start on silence.

Show, for every plan: tier, staleness, conflict table, source gaps, and the operator checklist. Ask which unit to start from, whether Step 6 opens **drafts** or **ready for review**, and whether the checklist is done. Begin Step 3 only after the user answers.

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
6. Dispatch `plan-auditor` with the brief path, the report path, and the diff path.
7. Apply the audit result:
   - `HALT`: stop the run, show the finding, and wait.
   - `FAIL` or an `Important` finding: dispatch `plan-implementer` with the findings, at most twice. After each fix, write a new diff from the previous review's HEAD and dispatch `plan-auditor` on that diff only.
   - `Minor`: copy it into the ledger. It does not block the next unit.
   - Gate `FAIL`: the implementer re-runs the gate and appends the tail before you mark the unit complete.
8. Append `Unit <NN>: complete (commits <base>..<head>, review <clean|N minor>)`.

A commit is done only when the report shows a green focused run and a green full gate. You do not weaken a gate the plan names.

## Step 4 — Final review

After the last unit, write `branch.diff` for `git diff <base>...HEAD`.

- **Lightweight:** read that diff yourself against the plan's scope. Dispatch `plan-final-review` only if you find a concrete risk.
- **Standard or full:** dispatch `plan-final-review` once, with the plan path, `branch.diff`, and the ledger.

If it returns findings, dispatch one `plan-implementer` with the full list, then one `plan-auditor` on the fix diff. A residual that contradicts the plan is `HALT`. Any other residual goes in the ledger and in the Step 6 report. There is no second fix wave.

## Step 5 — Stacked pull requests

The checkpoint answer authorizes this step. Ask again only when a step below fails.

1. Confirm `gh auth status` and `gh stack --help`. If the extension is missing, stop and report `gh extension install github/gh-stack`. Do not install it.
2. Adopt the unit branches without changing their commits: `gh stack init --base <base> <unit-01> ... <top>`, then `gh stack view`. Every branch must have its intended parent. If one does not, stop.
3. Submit with `gh stack submit --auto` for drafts, or `gh stack submit --auto --open` for ready for review.
4. Set each body with `gh pr edit <branch> --body-file <file>`. The body is a short summary, then `## Source`, one source per line:

```text
## Source

- Asana: <task URL>
- GitHub: Closes #<n>
- GitHub: Refs #<n>
- Aikido: <issue id> <issue link>
```

A GitHub issue is `Closes` on the last unit that delivers it and `Refs` on every earlier one. Keep those prefixes. `rs-gh-stack-merge` parses them. End with the attribution line this harness supplies, when it supplies one.

5. Record every PR URL, its sources, and the final `gh stack view` in the ledger.

Done when every layer has a non-empty `## Source`. Do not merge, force-push, or rewrite commits.

## Step 6 — Report

Print, per plan: path, tier, units completed, audit results, any `HALT`, residual findings, PR URLs, and the ledger path. The ledger is gitignored, so this report is the copy a later reader can see.

---

## Standing rules

- One implementer at a time, on the checked-out unit branch. A later unit's branch does not exist until the earlier unit has committed.
- The brief file is the unit's requirements. The task prompt points at it.
- Where the plan and the code disagree, the code wins. Record the disagreement. If the unit then cannot be implemented as written, `HALT` and ask.
- Reviewer agents have `edit: deny`. If you ask one to change a file, the tool will fail.
