---
description: Implement a written plan serially, escorted by read-only review agents, with one approval checkpoint before any code is written
argument-hint: <plan-path>
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Agent
---

Plan: $1

You are the **implementer** and the team lead. You are the only agent in this run that writes to the
working tree. Every other agent you spawn is read-only and exists to check your work.

Run log: `docs/cc_logs/<plan-filename-stem>_run.md` (create `docs/cc_logs/` if missing; it is
gitignored). If that file already exists, append a new dated section rather than overwriting it.

---

## Step 1 — Pre-flight

Read the plan in full. Then spawn a single teammate named `scout` using the `preflight-scout` agent
type, and give it the plan path and this brief:

> Compare the plan at `<path>` against this repository as it is right now. Read the actual files the
> plan names — never trust the plan's description of the code. Produce **one markdown table, one row
> per plan commit**, with exactly these columns:
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

## Step 2 — The checkpoint

**Stop here.** This is the only scheduled stop in the run.

Show the user the scout's table and blockers, and ask which commit the run should start from and
whether to proceed. Do not begin implementing until the user answers. If the user does not respond,
the run does not start.

## Step 3 — Implementation

Walk the plan's commits **in order**, starting where the user said. Never work on two commits at
once, and never reorder them — the ordering is the plan's safety property.

For each commit:

1. Make the change exactly as the plan specifies.
2. Run the plan's gate command for that commit (`make test`, `make lint`, whatever the plan names).
3. **Commit only once the gate is green.** A red gate is fixed before committing, never after. Fix
   forward applies to *reviewer findings only*, never to gate failures.
4. Append to the run log: the commit subject, the gate command you ran, and the **tail of its real
   output**. This is the evidence that the gate actually ran; a run log entry without it is treated
   as a skipped gate.
5. If the scout marked this commit `moderate` or `high`, run Step 4 before moving on. If it marked it
   `mechanical`, move on.

## Step 4 — Per-commit audit (risky commits only)

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

Reuse the same auditor across commits by messaging it rather than spawning a new one each time.

Then:

- **Ordinary findings** → fix them yourself as a follow-up commit, gated and logged like any other.
  Record in the run log what was found and what you did.
- **A `HALT` finding** → stop the run, report it to the user, and wait. This is a scope question and
  it is not yours to settle.

## Step 5 — Final review

After the last plan commit, **you** spawn the lenses — a teammate cannot spawn teammates, so this
fan-out has to come from here. Spawn all three in parallel over the full branch diff
(`git diff <base>...HEAD`, base being the commit the run started from):

- `correctness-lens` — broken call sites, deletions whose callers survive, behaviour that silently
  changed, error and state paths that differ from before.
- `framework-lens` — is this the current correct idiom for the versions **actually installed** in
  this repo? Check the API surfaces the diff calls and the version constraints it assumes.
- `guidance-compliance-lens` — did this change require updating `CLAUDE.md`, `AGENTS.md`, and
  `.github/copilot-instructions.md` per this repo's own rule, and do those files still describe the
  code truthfully?

Give each the plan path, the diff range, and an instruction to **message its findings to the lead**
and to read the real source files. If a lens should use the repo's review tooling, say so in its
spawn prompt — a `skills:` field in an agent definition is ignored for teammates, so it cannot be
preloaded.

## Step 6 — Report

Write the lens findings into the run log, then **also print them to the terminal**. The run log is
gitignored, so anything that exists only there is invisible to any later reader.

Report to the user: the plan path, commits made, commits audited and what the audits found, what was
fix-forwarded, any `HALT` you hit, the outstanding lens findings you did **not** act on, and the run
log path.

Do not push. Do not open a pull request.

---

## Standing rules

- You are the only writer. If you catch yourself asking a review agent to change something, stop —
  they have no write tools and the request will fail.
- Reviewers must be told to message their findings. An idle notification tells you a teammate
  stopped; it does not carry its output.
- Never mark a commit done on a gate you did not run.
- Where the plan and the code disagree, the code wins, and the disagreement goes in the run log.
