---
description: Turn GitHub issues (all open, specific numbers, or one assignee's) into a right-sized implementation plan
agent: build
model: opencode-go/glm-5.3-flash
---

> **Harness note.** This workflow was written for Claude Code conventions (frontmatter
> `allowed-tools`, `AskUserQuestion`). OpenCode handles all of this inline: ask the user with the
> `question` tool where a confirmation is called for. Every other rule applies unchanged.

Arguments: $ARGUMENTS

## Step 0 — Collect the issues

Parse the arguments into an issue selector and an optional output path (an argument
ending in `.md`):

- empty or `all` -> every open issue:
  `gh issue list --state open --limit 500 --json number,title,labels,assignees,url`
- issue numbers or URLs -> exactly those issues.
- `@<login>` (or `@me`) -> open issues assigned to that person:
  `gh issue list --state open --assignee <login> --limit 500 --json number,title,labels,assignees,url`

If a listing returns exactly 500 issues it is capped: say so and ask the user to narrow the
selector rather than presenting it as complete.

Then read every selected issue in full, comments included:
`gh issue view <n> --comments --json number,title,body,state,labels,assignees,comments,url`.
Collecting is done when every selected issue's body and every comment has been read. If
a named issue is closed, or the selection is empty, tell the user and stop. If `gh` is not
authenticated, ask the user to run `! gh auth login`.

The issues are the input set. Group them by the subsystem they touch; issues that touch
independent subsystems become separate plans, one per group. When there is more than one group and the arguments give
an output path, use it as a prefix: write `<path without .md>-<group-slug>.md` per group.

## Steps 1–5 — Plan

Read `.claude/commands/rs-plan-from-brainstorm.md` and run its output-path rule and Steps
1–5 exactly, with these substitutions:

- **The brainstorm doc** is the issue set collected above. The output path is the one from
  the arguments, else the brainstorm command's default (today's date).
- **Settled decisions** are only the behavior an issue states explicitly and anything a
  maintainer confirmed in its comments. Everything else — vague acceptance criteria,
  competing proposals in comments, unstated expected behavior — is open: resolve it from
  the code, or ask with `AskUserQuestion`.
- **Scope** cites every issue it implements by number and URL, and names selected issues
  the plan deliberately leaves out, with the reason.
- **Step 2** (structure and naming) covers the files the issue set requires: show the tree, contents,
  and sample names, and wait for the user's approval before drafting, exactly as for a brainstorm.
- **Each stack unit** names the issues it closes, so its PR body can carry `Closes #<n>`.
  An issue closed across several units is closed by the last one.

Planning only reads GitHub: it never comments on, labels, assigns, or closes issues.
