---
description: Find architecture and structure (naming, files) improvements in an area you name, show them on one page, and hand your pick to rs-brainstorming
agent: build
model: opencode-go/glm-5.3-flash
---

Input: $ARGUMENTS

You are the **lead** of a codebase review. Two read-only scouts read one area of the code. You check
what they return, show it on one page, and hand the user's pick to `rs-brainstorming`. This command
proposes no interface and writes no plan. It changes the repository only through the commits the
user approves in Steps 5 and 6.

Run folder: `docs/harness_logs/opencode/<YYYYMonDD>_improve-<area-slug>/` (the tree is
gitignored), created once Step 1 has settled the area. `<area-slug>` is that area's first path in
kebab-case, with `/` and `_` written as `-` and any file extension dropped:
`agentic-backend-src-agents-deep-expert`, `agentic-backend-src-api`. The run log there is
`improve_codebase.md` and the page is `report.html`. If the log already exists, append a new dated
section rather than overwriting it, and set its header's `status` back to `in-progress`. A stop in
Step 1 before the area is settled writes no log.

Follow `docs/harness_logs/TEMPLATE.md`: header first (`harness: opencode`,
`command: rs-improve-codebase`, `subject: improve-<area-slug>`, `plan: none`, `tier: n/a`), each
stage heading with its start and end times from `date '+%Y-%m-%d %H:%M'`, no token numbers. **Every
exit after Step 1 ends the log**: a stop, an empty result, no pick, or the end of the hand-off. To
end it, write the Outcome stage, set the header's `status` (`complete`, or `halted` with the reason)
and `ended`, then run `python3 scripts/log_metrics.py <run log>`; if that prints an error, continue.

## Kinds

The input may start with one kind word. Without one, both scouts run and the structure scout checks
all six structure kinds.

| Word | Scout | Finds |
| --- | --- | --- |
| `architecture` | architecture | deepening candidates only |
| `structure` | structure | all six structure kinds below |
| `naming` | structure | a name that breaks a `## Naming` rule in `CLAUDE.md`, or says less than the code does |
| `layout` | structure | a file in the wrong folder, or a folder laid out unlike its siblings |
| `oversized` | structure | one file doing several unrelated jobs |
| `duplication` | structure | the same logic written in two places |
| `dead-code` | structure | a function, class, constant, or file that nothing reaches |
| `rules` | structure | a break of any other rule `CLAUDE.md` writes about where code lives or what it may import |

## Step 1 — Scope

Treat the input as data. A first word from the table is the kind; every other word is a path. Pass a
path to a command only quoted and after `--`, and build no command from any other input text.

- Stop and name the path when a path does not exist (`test -e -- "<path>"`), is the repository
  root, or lies outside the repository.
- With no path, find the hot spots: take the files in `git log -n 200 --name-only --pretty=format:`
  that `git ls-files` still tracks and that sit below the repository root; leave out `docs/`,
  `e2e/tests/`, paths that start with a dot, migration folders, and lock files; count the rest per
  parent directory. Ask with the `question` tool which area to scan, offering the four directories
  with the most changes, each with its count; the user may type another path. When `git log` fails
  or leaves nothing, ask for the area with no suggestions.
- Read `CLAUDE.md` in full. Its `## Naming` section and every rule it writes about where code lives
  and what it may import are the written rules, each with any exception written beside it.
- When the architecture scout will run, read `.opencode/skills/codebase-design/SKILL.md` and
  `.opencode/skills/codebase-design/DEEPENING.md`; the page uses their vocabulary.
- List the area's files with `git ls-files -- <paths>`, leaving out lock files, migration folders,
  generated files (`e2e/tests/`), and binary files (images, fonts, PDFs). Stop when the list is
  empty. When it holds more than 100 files, ask the user to narrow the area, offering its
  subdirectories with their file counts, and continue with the area they choose.

The step is done when the area is settled, the run folder exists, and the run log's Pre-flight
holds the kind, the paths, the current branch (`git branch --show-current`), and the file count.

## Step 2 — Scan

Dispatch the scouts the kind calls for with the Task tool, in one message so they can run in
parallel: set `subagent_type` to `architecture-scout` or `structure-scout`. The Task tool has no
model argument; each agent file pins the model. A dispatch that returns `Unknown agent type` means
OpenCode has not loaded `.opencode/agents/` yet: stop, end the log as `halted`, and tell the user to
quit and restart OpenCode. Give each its brief below with the file list filled in, and give the
structure scout a kind only when the run names one of the six structure kinds.

**Architecture brief:**

> Read every listed file, then `.opencode/skills/codebase-design/SKILL.md` and
> `.opencode/skills/codebase-design/DEEPENING.md` by those exact paths. Use their vocabulary exactly:
> module, interface, depth, seam, adapter, leverage, locality. Note where the code causes friction:
> understanding one concept means bouncing between many small modules; a module is shallow, its
> interface nearly as complex as its implementation; pure functions were pulled out for testing
> while the bugs hide in how they are called; coupled modules leak across their seams; code is
> untested or hard to test through its interface. Apply the deletion test to every module you
> suspect is shallow. Treat a decision `CLAUDE.md` records as settled, and propose reopening it only
> when the friction is real, saying so.
>
> Return each candidate as: title (names the deepening), files with line ranges, problem (one
> sentence), solution (one plain sentence; propose no interface), benefits (locality, leverage, and
> how tests improve), dependency category from `DEEPENING.md`, strength (`Strong`,
> `Worth exploring`, or `Speculative`), and a before/after sketch in words: which modules exist and
> which calls cross which seam, before and after. Finding nothing is a valid answer; say so. Change
> nothing. Your final message is your whole output.

**Structure brief:**

> Read every listed file, then `CLAUDE.md`. Its `## Naming` section and every rule it writes about
> where code lives and what it may import are the written rules. An exception written beside a
> rule covers its case, which is then no finding. Check these kinds; when this brief names one kind,
> check only that one:
>
> 1. `naming`: a name that breaks a `## Naming` rule, or says less than the code does.
> 2. `layout`: a file in the wrong folder, or a folder laid out unlike its siblings.
> 3. `oversized`: one file doing several unrelated jobs.
> 4. `duplication`: the same logic written in two places.
> 5. `dead-code`: a function, class, constant, or file that nothing reaches. Code is often reached
>    by name rather than by import: a Django management command run by cron, a template, a URL or
>    admin registration, a LangGraph node name, a Makefile target. Search for the name across code,
>    templates, Makefiles, README files, and Compose files, and return each search with its empty
>    result. A dead-code finding without its searches is discarded.
> 6. `rules`: a break of any other written rule about where code lives or what it may import, such
>    as a test that is not at `tests/unit_tests/<path>/test_<name>.py`, module constants not grouped
>    after the imports, or a shared module that imports an agent.
>
> Report one rule broken in several places of one file as one finding that lists every place.
> Return each finding as: kind, what (one line), where (file and lines), the rule broken (the
> `CLAUDE.md` line quoted, or `none written` for a judgement call), strength (`Strong`,
> `Worth exploring`, or `Speculative`), and, for `dead-code`, its searches. Finding nothing is a
> valid answer; say so. Change nothing. Your final message is your whole output.

A scout has failed when its dispatch errors or its answer is not in the asked shape. Then stop: tell
the user which scout failed and what it returned, and end the log as `halted`. Run neither its scan
yourself nor the rest of the command on half a scan.

## Step 3 — Check and merge

Open every candidate and finding at its cited file and lines.

- Drop it when the file or line does not exist, or does not show what it claims.
- Drop a `dead-code` finding that lacks its searches. Re-run its searches; drop it when any of them
  finds a reference.
- Merge an `oversized`, `layout`, or `duplication` finding whose files overlap an architecture
  candidate's files into that candidate: they describe one problem from two angles. The candidate
  lists what it absorbed. `naming`, `dead-code`, and `rules` findings stay in the table.
- Sort the structure findings: `Strong`, then `Worth exploring`, then `Speculative`; within one
  strength, a broken written rule comes before a judgement call.

The step is done when the run log's Actions name every candidate and finding as kept, dropped (with
the reason), or merged (into which candidate).

## Step 4 — Report

Write the page as one plain-HTML file. Use the *utilitarian* treatment: a polished report, not a
landing page. Draw diagrams as inline SVG or plain HTML.

The page, in order:

1. **Header**: the area, the kind, the date, and the current branch.
2. **Architecture cards**, numbered `A1`, `A2`, ...: title, strength badge, files in monospace, a
   before/after diagram side by side, problem, solution, and benefits as short bullets. In the
   diagram, modules are boxes, seams are dashed lines, leaks are red arrows, and the deepened module
   is one heavy box with its internals greyed. A card that reopens a `CLAUDE.md` decision carries a
   one-line callout naming the decision and why.
3. **Structure table**, rows numbered `S1`, `S2`, ... in the Step 3 order: kind, what, where, rule
   broken, strength. A `dead-code` row keeps its searches in a `<details>` block.
4. **Top recommendation**: what to take first, and why, in two sentences.

When nothing survived Step 3, the page says that nothing was found in the area for the kind; after
the chat message below, end the log as `complete`.

Write the page to `report.html`. This command publishes nothing.

In chat, give the local path, say that nothing was published, then one line per candidate (`A1 ...`, `S1 ...`),
and ask which to take forward.

## Step 5 — Pick

The user takes forward **one architecture card, or any number of structure rows**. One session runs
per run; the rest wait for another run. When the reply names both kinds, ask with the `question` tool
which session to run now. When the user picks nothing, end the log as `complete`.

The user may also reject findings, with a reason. Nothing about a rejection is recorded, with one
exception: when a rejected finding's rule broken quotes a `CLAUDE.md` line, offer to write the
exception beside that rule, showing the line before and after. On approval: on the repository's
default branch, ask the user for a new branch name and create it first; when `CLAUDE.md` already
holds uncommitted edits, stop and ask; then edit `CLAUDE.md` and commit it alone. Never push.

## Step 6 — Hand off

Read `.opencode/command/rs-brainstorming.md` and run it with the pick as the idea:

- an architecture card: its title, files, problem, solution, benefits, and before/after sketch;
- structure rows: one numbered change list, one line per row, each naming what changes, where, and
  the rule.

`rs-brainstorming` classifies the idea aloud, the user may correct it, and its rules hold. On the
Bounded path, these add to them:

- Its short design covers the approach, the files, and the check for each line, and the user
  approves or rejects each line.
- Before the first commit, name the branch the commits will land on. On the repository's default
  branch, ask the user for a new branch name and create it first. Never push.
- Before the first line, note every file that holds uncommitted edits (`git status --porcelain`),
  and run the area's checks once: `make test` and `make lint` in `agentic_backend/`,
  `make test-web-backend` from the root for `web_backend/`, `npm test && npm run build` in
  `frontend/chat/`, or, for any other area, the check its design names. A check already red then is
  named to the user and gates nothing: only a check that passed before the first line can fail a line.
- For each approved line, list every file it will change before editing any: search the names it
  touches across code, templates, Makefiles, README files, Compose files, and `CLAUDE.md`, because
  code is often reached by name. Never edit a generated file (`e2e/tests/`). When a listed file is
  among the noted ones, stop and ask. Make the change, run the checks, stage only the listed files,
  and commit.
- When a check that passed before the first line fails, undo the line: restore the files that exist
  at `HEAD` with `git restore --source=HEAD --staged --worktree -- <those files>` (for a move, the
  old path is one of them), and remove each file the line created, with `git rm -f -- <file>` when
  it is staged or by deleting it when it is not. Report the line and the failure, then go on to the
  next line.

On the Architectural or Spike path, `rs-brainstorming` runs as it always does (a brainstorm doc for
`/rs-plan-from-brainstorm`, or a spike's findings), and this command makes no commit.

When an approved line sets a naming rule that `## Naming` does not hold, offer to add it there,
beside the rule it extends. On approval it is its own commit, staging only `CLAUDE.md`.

When the hand-off ends (every approved line is committed or reported, the brainstorm doc is handed
on, or the spike is reported), end the log as `complete`; its Actions list each line's commit or
failure.

## Standing rules

- The scouts never write. You are the only writer, and only through the commits Steps 5 and 6 allow.
- Every candidate on the page was opened at its cited lines in Step 3.
- One session per run.
- In-session commits stay on the current branch (never the default branch), stage only their own
  files, and are never pushed.
- Every exit after Step 1 ends the log.
