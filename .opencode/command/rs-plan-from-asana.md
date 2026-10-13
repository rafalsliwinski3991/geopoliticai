---
description: Turn Asana tasks (specific tasks or one assignee's) into a right-sized implementation plan
agent: build
model: opencode-go/glm-5.3-flash
---

Arguments: $ARGUMENTS

## Step 0 — Collect the tasks

Use the Asana MCP server's tools. If no Asana tools are available or they are
unauthenticated, tell the user to connect an Asana MCP server and stop.

Parse the arguments into a task selector and an optional output path (an argument ending
in `.md`):

- task URLs or gids -> exactly those tasks. The gid is the numeric id in the URL's
  `/task/<gid>` segment (or the last numeric segment of older URLs).
- `@<name|email>` (or `@me`) -> that person's incomplete tasks. Resolve the person to an
  Asana user first; if the name matches several users, ask with the `question` tool.
- empty -> ask which tasks or assignee to plan from.

Then read every selected task in full: name, notes/description, custom fields, due date,
project, subtasks, attachments' names, and every comment (story). Collecting is done when
every selected task and its comments have been read. If a named task is completed, or the
selection is empty, tell the user and stop.

The tasks are the input set. Group them by the subsystem they touch; tasks that touch
independent subsystems become separate plans, one per group. When there is more than one group and the arguments give
an output path, use it as a prefix: write `<path without .md>-<group-slug>.md` per group.

## Steps 1–5 — Plan

Read `.opencode/command/rs-plan-from-brainstorm.md` and run its output-path rule and Steps
1–5 exactly, with these substitutions:

- **The brainstorm doc** is the task set collected above. The output path is the one from
  the arguments, else the brainstorm command's default (today's date).
- **Settled decisions** are only the behavior a task states explicitly and anything
  confirmed in its comments. Everything else — vague acceptance criteria, competing
  proposals in comments, unstated expected behavior — is open: resolve it from the code,
  or ask with the `question` tool.
- **Scope** cites every task it implements by name and URL, and names selected tasks the
  plan deliberately leaves out, with the reason.
- **Step 2** (structure and naming) covers the files the task set requires: show the tree, contents,
  and sample names, and wait for the user's approval before drafting, exactly as for a brainstorm.
- **Each stack unit** names the Asana task URLs it delivers, so its PR body can link them.

Planning only reads Asana: it never comments on, reassigns, or completes tasks.
