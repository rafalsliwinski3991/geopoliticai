---
description: Audit a written plan against the current repo and rewrite it as a new, self-contained, right-sized version with a changelog
agent: build
model: opencode-go/glm-5.3-flash
---
> **Harness note.** This workflow was written for Claude Code, which can spawn named read-only
> subagents (`preflight-scout`, `commit-auditor`, `correctness-lens`, `framework-lens`,
> `guidance-compliance-lens`). OpenCode has a subagent mechanism but none of those agents, so a
> literal dispatch errors on an unknown name. Wherever the steps below say to spawn one, perform
> that role yourself, in a separate pass, and report its findings under that agent's name. Every
> other rule applies unchanged.
>
> Step 5 dispatches `/opencode:rescue`, a Claude Code plugin command. OpenCode runs the critic
> itself, so run that critique as a separate, fresh read-only pass over the new plan and the
> repository files, briefed and reported exactly as Step 5 describes. It stays mandatory at every
> tier; only the dispatch changes.

Plan: $1

You are the **auditor and reviser** and the team lead. You are the only agent in this run that
writes. Every other agent you spawn is read-only and exists to check the plan, never to change it.

Run log: `docs/cc_logs/<plan-filename-stem>_improve_run.md` (create `docs/cc_logs/` if missing; it is
gitignored). If that file already exists, append a new dated section rather than overwriting it.

---

## Step 0 — Check the critic and resolve the new version path

Before anything else, confirm that the Step 5 OpenCode critic can run:

```bash
opencode models 2>/dev/null | grep -Fx 'opencode-go/muse-spark-1.3-contributor'
```

If it prints nothing, tell the user OpenCode or the model is unavailable and ask with
`AskUserQuestion` whether to **continue without the OpenCode critique** (skip Step 5) or **stop**.
Record the answer in the run log.

Read `$1`'s filename. It must end `_v<N>.md`; if it doesn't, treat it as `v1` for numbering purposes
but do not rename it. The new path is the same directory and stem with `_v<N+1>.md`. If any higher
version of the same stem already exists, `$1` is not the latest version: stop and ask the user with
`AskUserQuestion` whether to audit the newest version instead. Continue from `$1` only if the user
says so, and then use the next unused version number.

Do not create the new file yet; Step 4 writes it.

## Step 1 — Read

Read the plan in full. Then read every file, module, config, and test it names. Do not audit against
the plan's description of the code — audit against the code. Where they disagree, the code wins, and
every disagreement becomes a changelog entry in the new version, not a silent fix.

Identify the plan's stated tier: **lightweight**, **standard**, or **full**. If it
does not name one, infer the smallest safe tier from its scope. Preserve that tier
unless the live code reveals a concrete risk that requires escalation; do not enlarge
the plan merely because it is being reviewed. A lightweight plan is a minor contained
change, a standard plan is coherent multi-file work within one subsystem, and a full
plan covers major, risky, cross-component, interface, migration, or order-dependent
work. Record any escalation and its evidence in the changelog.

Settled decisions stay settled: the plan's own decisions, and those of the brainstorm or context doc
it names, are not options to reopen. When a finding would reopen one, or a blocker cannot be resolved
from the code, the plan, or its source doc, ask the user with `AskUserQuestion` instead of deciding
it in the rewrite.

When auditing a plan's use of an external framework or library, verify current
APIs and version-specific behavior through Context7: resolve the exact library
and version with `resolve-library-id`, then use `query-docs`. Treat installed
versions and checked-out repository code as the local constraints; do not use
Context7 for facts those sources already establish. For prior art or API guidance
outside library docs, use Tavily (`tavily_search`, `tavily_extract`), and cite every
web source the new version relies on.

## Stacked pull-request planning

When revising a plan, preserve or repair boundaries so the result can be
implemented as a GitHub stacked pull-request chain without rewriting history:

- Resolve and carry forward the trunk/base branch and a stable stack slug. Use
  the repository default branch unless the user specifies another base.
- Keep a lightweight plan as one unit when it is genuinely contained. For
  standard and full plans, every ordered task or commit must be one independently
  reviewable stack unit. Let each unit be one genuinely reviewable change.
- Each revised unit must name its proposed branch (for example,
  `<stack-slug>/01-<short-slug>`), parent branch, files, dependencies on earlier
  units, focused validation, and gate command. Units must work bottom-to-top
  without relying on uncommitted changes from another unit.
- If the source plan combines changes that need separate review, split them into
  ordered units and record that split in the changelog. If the source already has
  valid boundaries, preserve them and do not reorder them silently.
- If the bottom units are already merged into the base branch, make the base branch
  the parent of the first remaining unit.
- The revised plan must state that implementation creates one or more linear commits
  per unit branch, with reviewer fixes remaining on that branch, and that
  `rs-implement-plan` opens the pull requests itself, as a stack or one PR, when its
  checkpoint asks for them (`rs-create-stacked-prs` remains for hand-built branches).
  This workflow does not push, create, merge, or rewrite pull requests.

## Step 2 — Pre-flight scout

For a **lightweight plan**, inspect the named files and focused validation yourself.
Write a short status and staleness note into the run log; do not spawn a scout just to
produce one row for one contained change.

For a **standard or full plan**, spawn a single teammate named `scout` using the `preflight-scout` agent type, and give it the plan
path and this brief:

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
>   plan assumes, whether the plan's base branch has advanced since it was written, or `—` if clean.
>
> Below the table, list any **blockers**: plan sections that can no longer be implemented as written
> against the current code. Write nothing to disk and change nothing. Return the table and the
> blockers as your message to the lead — an idle notification carries no output, so you must send it
> explicitly.

Write the scout's table and blockers into the run log verbatim.

If every task or commit comes back `already applied` with no blockers, stop here: report to the user that
the plan appears fully implemented and ask whether they still want a new version (for example, to
record that fact) before spawning anything else in Step 3.

## Step 3 — Parallel critical review

For a **lightweight plan**, self-review the proposed change against the live code.
Check its exact behavior, focused validation, and applicable guidance. Do not dispatch review
agents unless a concrete discovery raises the plan's tier.

For a **standard plan**, spawn only `correctness-lens`. Give it the brainstorm or context doc this
plan was built from (if named), the plan path, and the scout's table. It must read actual source
files and return only severity-ranked correctness, regression, error-path, or test-gap findings.

For a **full plan**, spawn three teammates in parallel. Give each the brainstorm or context doc this plan was built from
(if the plan names one), the plan path, and the scout's table, and instruct each to read the actual
source files rather than trusting the plan's or the scout's claims about them. Unlike a post-run
review, there is no diff yet — these agents review the plan's **proposed** commits and code blocks
against the live repository, as if deciding whether to approve them before a single line is written.

- **`correctness-lens`** (agent type `correctness-lens`). Brief: For every commit in the plan, would
  applying it exactly as written leave the repo importable, runnable, and its tests passing? Hunt for
  proposed code that references symbols, signatures, or files that don't exist or don't match; plan
  steps that assume a state the scout's table says isn't there; deletions whose callers would
  survive; commits that depend on a later commit's output; error or state paths the plan's code would
  quietly handle differently than today.
- **`framework-lens`** (agent type `framework-lens`). Brief: For the frameworks, libraries, and
  versions actually installed in this repo right now, is the plan's approach still the current
  correct idiom? Check every API surface the plan's code blocks call, every version constraint the
  plan assumes, and whether a newer or older installed version has moved the ground since the plan
  was written. Use Context7's `resolve-library-id` and `query-docs` when authoritative current
  library documentation is needed.
- **`guidance-compliance-lens`** (agent type `guidance-compliance-lens`). Brief: Read `AGENTS.md`,
  `CLAUDE.md`, and `.github/copilot-instructions.md` as they exist right now. Does the plan's
  migration/rollout section correctly identify every one this repo's own rules require updating, and
  does it describe changes that are still accurate given what these files currently say? Also flag
  any place the plan itself now contradicts this repo's standing guidance.

Each must message its findings to the lead directly (an idle notification carries no output). Each
finding: ranked by severity, with a file path, a line (in the plan or in the source), and a concrete
failure scenario. No style notes, no praise, no summary of what the plan does well.

Write every lens's findings into the run log verbatim.

At every tier, then make a simplification pass yourself. Cut work the plan's goal does not need;
replace a new helper, abstraction, config option, or dependency with an existing local pattern, the
standard library, or an installed dependency when one does the job; and fold any unit not worth
reviewing on its own into its neighbor. Never cut tests, validation, or error handling the change
needs, and send any cut that would change a settled decision to the user (Step 1). Record each cut
in the run log.

## Step 4 — Write the new, complete version

Write the new version to the path resolved in Step 0. It is a new file; never modify `$1`. **It must
stand alone.** Someone reading only
this file, never opening the previous version, must get the full picture — do not write "see v1 for
the rest" or omit a commit because it didn't change. Carry forward everything from the previous
version that the scout and the lenses did not invalidate, and rewrite everything they did. Anything
you rewrite or add meets the bar a fresh plan of its tier must meet: exact files, behavior, and
validation commands, and for a full plan, real before/after code fitted to this repo, with imports
and both sides of any public interface it touches. Leave no placeholders such as `TBD`, "add
appropriate handling", or "write tests".

The new version keeps the previous version's tier and appropriate section structure: lightweight
plans keep scope, change steps, validation, and applicable follow-up; standard plans keep scope,
file responsibilities, ordered tasks, and test/follow-up notes; full plans keep scope summary,
file responsibilities, ordered commits with before/after code, test plan, migration and rollout
notes, and open questions. Add one more section immediately after the title:

**Changelog (v`<N>` → v`<N+1>`)** — one entry per substantive change from this round, each stating
what changed, which finding drove it (scout staleness, a named lens finding, or the simplification
pass), and why. Include
entries for commits marked `already applied` or `partially applied` by the scout and how the new
version accounts for that (mark them done and adjust the remaining ordering, rather than re-proposing
finished work). If a finding was surfaced but you rejected it, say so here with the reason, the same
way `rs-plan-from-brainstorm`'s "Open questions and rejected objections" section works — do not silently
drop a reviewer's finding.

Stop before implementing. Beyond the scout and the tier's lenses, the only remaining agent is the
Step 5 OpenCode critic.

## Step 5 — OpenCode critique of the new version

Runs for **every tier** — lightweight, standard, and full — once the new version exists on disk,
unless the user chose to skip it in Step 0.

Dispatch exactly one read-only OpenCode critic:

```text
/opencode:rescue --wait --fresh --model opencode-go/muse-spark-1.3-contributor --agent plan <task brief>
```

Brief it as a **read-only reviewer**: it must not modify files, create commits, or run destructive
commands. Give it the new plan path, the previous version's path, and the plan tier, and tell it to
read the actual repository files rather than trusting either plan's description of the code. Ask for
severity-ranked findings only — each with a file path, a line in the plan or the source, and a
concrete failure scenario — covering: proposed steps that would not apply cleanly to the current
code, missing or wrong ordering, unstated assumptions, validation the plan claims but does not
specify, scope the plan enlarged beyond its tier, and over-engineering — work the goal does not
need, or new code where an existing pattern or installed dependency would do — each with the simpler
alternative. No praise, no summary, no style notes.

Tell the critic to verify any external framework or library claim through Context7 rather than from
memory: resolve the exact library and installed version with `resolve-library-id`, then use
`query-docs`. Installed versions and checked-out repository code remain the local constraints — it
must not use Context7 for facts those sources already establish. If Context7 is unavailable to the
critic, it must say so and mark such findings as unverified instead of asserting them.

If the dispatch fails because the plugin or model is unavailable, ask the user the same Step 0
question: continue without the OpenCode critique, or stop. Never fall back to a Claude agent or
another model. When the user chooses to stop, delete the new version file (never `$1`) and record
the stop in the run log. When the critique is skipped, add a changelog entry saying the new version
had no OpenCode critique.

Write the critic's findings into the run log verbatim. Then fix the new version in place: apply
every finding you accept, and add a changelog entry for each — accepted or rejected, with the reason
— to the same **Changelog (v`<N>` → v`<N+1>`)** section. Do not create a further version file for
this round, and do not dispatch a second critic.

## Step 6 — Ask the user to approve the new version

Present the new version's path, tier, and complete changelog; the full plan is on disk at that path.
Then use `AskUserQuestion` to ask whether the user approves it. Offer these choices:

- **Approve** — keep the new version as written and continue to Step 7.
- **Request changes** — ask the user what must change, edit the new version in place, add a
  changelog entry for each change, and ask for approval again.
- **Cancel** — delete the new version file (never `$1`), record the cancellation in the run log, and
  stop.

Do not treat silence, ambiguous feedback, or a general conversational acknowledgment as approval.
The run leaves the new version on disk only once the user chooses **Approve**.

## Step 7 — Report

Report to the user: the previous plan path, the new plan path, the version bump, the plan tier,
and the applicable review summary. For a standard or full plan, include the scout's top-line status
(how many tasks or commits are already applied / partially applied / not started); for a lightweight
plan, include the direct pre-flight and self-review result instead. Also report how many findings
each applicable lens raised and how many you accepted, how many the OpenCode critic raised and how
many you accepted (or that the user chose to skip it), the simplifications you made, plus the
run-log path.

---

## Standing rules

- You are the only writer. If you catch yourself asking a review agent to change something, stop —
  they have no write tools and the request will fail.
- The Step 2 scout and every Step 3 lens run on the model and effort their agent definitions pin
  (Sonnet 5.5, medium effort); do not pass `model` when spawning them. The Step 5 OpenCode critic is
  not a Claude subagent and always uses `opencode-go/muse-spark-1.3-contributor`.
- Reviewers must be told to message their findings. An idle notification tells you a teammate
  stopped; it does not carry its output.
- The Step 5 OpenCode critique runs at every tier, before the user is asked to approve. Only the
  user can skip it, and only when OpenCode or the model is unavailable.
- Where the plan and the code disagree, the code wins, and the disagreement goes in the changelog.
- The new version is a complete replacement, never a diff or a pointer back to the old one.
- Never claim a finding was addressed unless the new version's text actually reflects it.
