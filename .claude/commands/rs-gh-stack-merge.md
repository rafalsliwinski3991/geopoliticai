---
description: Merge every pull request of a gh-stack chain, then close the Asana tasks, GitHub issues, and Aikido issues they deliver
argument-hint: "[optional stack number, PR number, or branch in the stack]"
allowed-tools: Read, Write, Glob, Grep, Bash, AskUserQuestion, mcp__asana, mcp__plugin_aikido_aikido-mcp__aikido_issues_list
---

Stack input: $ARGUMENTS

You are the **merger** of a stacked pull-request chain. You merge the whole chain into its trunk in
one atomic `gh stack merge`, then close every source its PRs name. You never edit code, push, or
rewrite commits.

Run log: `docs/harness_logs/<stack-slug>_stack_merge.md` (create `docs/harness_logs/` if missing; it is
gitignored). If it exists, append a new dated section.

Follow `docs/harness_logs/TEMPLATE.md`: header first (`harness: claude-code`), one `date` stamp per stage heading, no token numbers. As the last step before the report, run `python3 scripts/log_metrics.py <run log>`; if it prints an error, continue.

---

## Step 1 — Resolve the stack

Confirm `gh auth status` succeeds and `gh stack --help` is available; if the extension is missing,
stop and report `gh extension install github/gh-stack`.

Start from the stack, PR, or branch in `$ARGUMENTS`, else the current branch. Run `gh stack view`
and read the layers bottom to top. For each layer fetch its PR:

```bash
gh pr view <branch> --json number,url,title,body,state,isDraft,baseRefName,headRefName,mergeable,reviewDecision,statusCheckRollup
```

Stop and report, rather than merge, when a layer has no PR, a PR's base is not the layer below it
(the bottom layer's base is the trunk), or a PR is a draft, conflicting, or failing required
checks. Already-merged layers are skipped and said so.

## Step 2 — Collect the sources

Parse each PR body's `## Source` section. Every line has one of these forms:

- `- Asana: <task URL>` — the task gid is the numeric id in the URL's `/task/<gid>` segment (or its
  last numeric segment).
- `- GitHub: Closes #<n>` or `- GitHub: Refs #<n>` — issue `<n>` in this repository.
- `- Aikido: <issue id> <issue link>`.

The sources to close are every Asana task, every `Closes` issue, and every Aikido issue across the
merged layers. A `Refs` issue closes only when some layer also carries `Closes` for it. A PR with no
`## Source` section, or a line in no known form, goes in the run log's "manual" list; never guess a
source.

The step is done when the run log holds a table: layer, PR, sources.

## Step 3 — Confirm and merge

Show the table and ask exactly one question with `AskUserQuestion`:

- **Merge with squash** — `gh stack merge <stack> --yes --squash`
- **Merge with a merge commit** — `gh stack merge <stack> --yes --merge`
- **Merge with rebase** — `gh stack merge <stack> --yes --rebase`
- **Cancel** — change nothing.

The merge is all-or-nothing:
if it fails, report GitHub's reason, close no sources, and stop. If the trunk uses a merge queue,
wait until every PR reports `MERGED` before Step 4.

## Step 4 — Close the sources

Only sources of PRs now in state `MERGED` are closed. Skip any source already closed.

- **GitHub** — `gh issue close <n> --reason completed --comment "Delivered by #<pr>."`
- **Asana** — `mcp__asana__add_comment` with `Delivered by <pr URL>`, then
  `mcp__asana__update_tasks` with `completed: true`. If the Asana tools are absent or
  unauthenticated, tell the user to run `/asana-setup` and list the tasks left open.
- **Aikido** — Aikido has no close action: it resolves an issue when its next scan of the trunk no
  longer finds it. Read the issue with `aikido_issues_list` and `issue_id`, and report it as
  resolved or as awaiting Aikido's next scan. Never ignore an issue to close it.

The step is done when every source is closed, reported as awaiting its scan, or listed with the
error that kept it open.

## Step 5 — Report

Report the merged PRs with the merge method, every source with its final state, the "manual" list,
and the run log path. Leave local and remote stack branches in place.
