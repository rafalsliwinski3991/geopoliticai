---
description: Turn Asana tasks (specific tasks or one assignee's) into a right-sized implementation plan
argument-hint: [<task-url|task-gid>... | @<assignee>] [output-plan-path]
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent, WebFetch, WebSearch, AskUserQuestion, mcp__asana, mcp__context7__resolve-library-id, mcp__context7__query-docs, mcp__plugin_context7_context7__resolve-library-id, mcp__plugin_context7_context7__query-docs
---

Arguments: $ARGUMENTS

## Step 0 — Collect the tasks

Use the official Asana plugin's MCP server (`mcp__asana__*` tools). If those tools are
absent or unauthenticated, tell the user to run `/asana-setup` (then `/mcp` to sign in)
and stop.

Parse the arguments into a task selector and an optional output path (an argument ending
in `.md`):

- task URLs or gids -> exactly those tasks. The gid is the numeric id in the URL's
  `/task/<gid>` segment (or the last numeric segment of older URLs).
- `@<name|email>` (or `@me`) -> that person's incomplete tasks. Resolve the person to an
  Asana user first; if the name matches several users, ask with `AskUserQuestion`.
- empty -> ask which tasks or assignee to plan from.

Then read every selected task in full: name, notes/description, custom fields, due date,
project, subtasks, attachments' names, and every comment (story). Collecting is done when
every selected task and its comments have been read. If a named task is completed, or the
selection is empty, tell the user and stop.

The tasks are the input set. Group them by the subsystem they touch; tasks that touch
independent subsystems become separate plans, one per group. When there is more than one group and the arguments give
an output path, use it as a prefix: write `<path without .md>-<group-slug>.md` per group.

## Steps 1–4 — Plan

Read `.claude/commands/rs-plan-from-brainstorm.md` and run its output-path rule and Steps
1–4 exactly, with these substitutions:

- **The brainstorm doc** is the task set collected above. The output path is the one from
  the arguments, else the brainstorm command's default (today's date).
- **Settled decisions** are only the behavior a task states explicitly and anything
  confirmed in its comments. Everything else — vague acceptance criteria, competing
  proposals in comments, unstated expected behavior — is open: resolve it from the code,
  or ask with `AskUserQuestion`.
- **Scope** cites every task it implements by name and URL, and names selected tasks the
  plan deliberately leaves out, with the reason.
- **Each stack unit** names the Asana task URLs it delivers, so its PR body can link them.

Planning only reads Asana: it never comments on, reassigns, or completes tasks.
