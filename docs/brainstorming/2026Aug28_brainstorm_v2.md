# Custom command: `/plan-to-team` — hand a plan path to Claude Code and have an agent team implement it

**Started:** 2026-08-28
**Status:** Complete (frontier empty)
**Mode:** single (one question per round, default)

## Context verified

- Repo root `/home/rafal/repos/geopoliticai`. Existing brainstorms for today: `v1`, so this session claims `v2`.
- Claude Code **v2.1.251** installed. `tmux` present at `/usr/bin/tmux` (WSL2).
- **Agent teams are already enabled for this project**: `.claude/settings.json` has
  `"env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" }`, and the running session has the
  env var set. So a command that "uses agent teams" will actually get teammates, not subagents.
- Existing custom command: `.claude/commands/plan-from-brainstorm.md` — takes a brainstorm path,
  writes a plan, then spawns **three review subagents** (correctness / domain-framework /
  devil's advocate), revises, and explicitly does **not** implement. The new command is the
  next link in that chain.
- No `.claude/agents/` directory exists in this repo, and none in `~/.claude/agents/`. There are
  no reusable subagent definitions yet — every persona today is inlined as prose in a command.
- **Shape of this repo's plans** (`docs/plans/`, 7 files, 156–2304 lines): each is a list of
  *ordered commits on one branch*, mechanical/low-risk first, riskiest rewrite last, every commit
  naming files touched and an exact test command that must pass before the next one starts. The
  latest (`2026Aug28_plan_for_simplification_v1.md`, 1086 lines) has commits that repeatedly touch
  the same files (`api.py`, `graph.py`, `models.py`).
- Official docs (`code.claude.com/docs/en/agent-teams`, v2.1.178+ semantics):
  - Teams: each teammate is a full independent Claude Code session, own context, no lead history;
    they share a **task list** (with dependencies + file-locked claiming) and a **mailbox**.
  - Anthropic's stated sweet spots: research/review, **new modules or features**, competing-hypothesis
    debugging, cross-layer (frontend/backend/tests) work.
  - Anthropic's stated anti-patterns, verbatim: *"For sequential tasks, same-file edits, or work with
    many dependencies, a single session or subagents are more effective."* Also *"Avoid file conflicts:
    two teammates editing the same file leads to overwrites."*
  - Recommended size: **3–5 teammates**; 5–6 tasks per teammate; "three focused teammates often
    outperform five scattered ones."
  - Teammate roles can come from **subagent definitions** (`.claude/agents/*.md`), referenced by name
    when spawning. For in-process teammates the definition's body is *appended* to the default system
    prompt (split-pane replaces it), `tools` is honoured, `skills` is **not** applied.
  - Teammates **cannot spawn teammates** (no nested teams); lead is fixed; permissions are the lead's
    and teammate permission prompts surface in the lead session.
  - Idle notification tells the lead a teammate stopped but **does not carry its output** — results
    must travel by explicit message or task-list update.
  - Quality gates available as hooks: `TeammateIdle`, `TaskCreated`, `TaskCompleted` (exit 2 = reject
    + feedback).
  - Known limits: `/resume` does not restore in-process teammates; task status lags; teammates
    sometimes stop early; token cost scales linearly with teammates.
  - `isolation: worktree` exists on subagent definitions (git worktree per agent).


## Target design

A custom slash command, `.claude/commands/implement-plan.md`, taking a plan path as `$1`
(plans live in `docs/plans/`). It drives a **serial implementer escorted by non-writing reviewers** —
parallelism lives in verification and review, never in editing.

**Agents.** Four roles. `preflight-scout` and `commit-auditor` (plus the end-of-run lenses) are
`.claude/agents/*.md` definitions that carry **capabilities only** — `tools` (no `Write`/`Edit`),
`model`, one line of role — with every word of task instruction supplied by the command's spawn
prompt. The **implementer** is the lead itself, briefed inline in the command file, and is the only
writer. Built-in `code-review`, `security-review`, and `simplify` skills are delegated to rather than
reimplemented; note `skills:` in a definition is ignored for teammates, so they must be requested in
the spawn prompt.

**Flow.**

1. **Preflight.** `preflight-scout` reads plan and repo and emits **one table, one row per plan
   commit**: status (already applied / partially applied / not started), risk, staleness note
   (moved paths, changed line numbers, dependency versions, whether `main` advanced). Every
   "mechanical" risk verdict carries a one-line justification naming what was checked.
2. **The single checkpoint.** The run halts, shows the table, and waits. The user approves and says
   where the run starts. This is the only scheduled stop.
3. **Implementation.** The implementer walks the plan's commits in order. For each: make the change,
   run the plan's gate command, and **commit only once the gate is green** — fix-forward applies to
   reviewer findings, never to gate failures. The gate command and the tail of its real output go
   into the run log per commit.
4. **Per-commit audit.** On commits the scout marked risky, `commit-auditor` reads `git diff HEAD~1`
   against that plan section: does this do what the plan said, and only that? It also checks the run
   log's gate evidence. Findings become follow-up fix commits. The auditor may **halt** the run for
   plan contradictions only — the diff does something the plan never asked for, or the section is
   unimplementable as written.
5. **Final fan-out.** After the last commit, **the lead** (teammates cannot spawn teammates) spawns
   2–3 independent lenses over the full diff: correctness, framework idiom, and a guidance-file
   compliance check that CLAUDE.md / AGENTS.md / `.github/copilot-instructions.md` were updated as
   this repo's rules require. Every reviewer is told to write findings to a file or message the lead,
   because an idle notification carries no output.
6. **Deliverable.** A run log at `docs/cc_logs/<plan-filename-stem>_run.md` — per-commit gate output,
   auditor findings, lens findings, and what was fix-forwarded. `docs/cc_logs/` is gitignored, so the
   final report **also prints findings to the terminal**. No automatic push or PR.

**Files this creates:** `.claude/commands/implement-plan.md`, `.claude/agents/preflight-scout.md`,
`.claude/agents/commit-auditor.md`, the lens definitions, a `docs/cc_logs/` entry in `.gitignore`.

## Settled decisions

- **Serial implementer, parallel escort (Q1)** — the team does not split implementation across
  teammates. One agent implements the plan's commits in order; the other agents review and verify.
  _(rationale: the repo's plans are sequential, same-file, dependency-heavy — the exact shape
  Anthropic's docs name as an anti-pattern for teams; the commit ordering is the safety property
  and parallelising discards it.)_
  - Challenged on: if the escorts don't write, this is subagent work — cheaper, and subagent
    results actually return to the caller, whereas a teammate's idle notification carries no output
    → held; user wants review agents bracketing implementation, and steerability of live agents is
    the differentiator.
  - Consequences: no worktree-per-implementer needed; no file-ownership partitioning; the
    "team" question narrows to *how review agents are spawned and how their findings return*.

- **Review granularity: bracket the run + risk-gated per-commit review (Q2)** — pre-run pass once,
  post-run full-diff pass once, and a per-commit review only on commits the plan flags as risky.
  _(rationale: the plan's own ordering already ranks risk — mechanical first, riskiest rewrite last
  — so review attention follows a signal the plan already carries.)_
  - Challenged on: no existing plan carries a machine-readable risk marker, so this either guesses
    from prose or forces a change to `plan-from-brainstorm.md` → see Q3 fallout; carried as an open
    dependency.
  - Consequences: opens **who emits the risk marker** and **what the command does with the seven
    existing plans that have none**.

## Design tree

- **Team as executor?** — SETTLED (Q1): serial implementer + non-writing escorts.
  - **Review granularity** — SETTLED (Q2): bracket run + risk-gated per-commit.
    - Risk marker ownership — SETTLED (Q5): the `preflight-scout` classifies.
  - **Commit / rollback semantics** — SETTLED (Q3): commit-as-you-go, fix forward.
    - Unconditional orphan check — SETTLED (Q12): dropped, accepted risk.
  - **Persona roster** — SETTLED (Q4): four phase personas + end-of-run lens fan-out.
    - Persona storage — SETTLED (Q8): hybrid — read-only personas as definitions, implementer inline.
    - Who spawns the fan-out (nested-team constraint) — SETTLED by docs: the lead must.
  - **Gate enforcement mechanism** — SETTLED (Q6): prose only, no hooks.
  - **Run control** — SETTLED (Q7): one hard checkpoint after the preflight-scout.
  - **Command contract / partial-progress handling** — SETTLED (Q9): scout reports per-commit
    progress; the user decides at the checkpoint.
  - **End-of-run deliverable** — SETTLED (Q10): a run log at `docs/cc_logs/`; no automatic PR.
  - Worktree-per-teammate isolation — PRUNED by Q1: nothing writes in parallel, so per-agent
    worktrees buy nothing.

- **Commit-as-you-go, fix forward (Q3)** — the implementer commits each plan commit for real;
  reviewers read `git diff HEAD~1`; a rejection becomes a follow-up fix commit rather than an amend.
  _(rationale: guaranteed exit from the review loop, clean audit trail of what review caught, and
  `git rebase -i` can collapse the noise afterwards.)_
  - Challenged on: fix-forward leaves rejected commits broken in history, defeating bisect and the
    "every commit leaves the repo runnable" property → see round 3 note.
  - Consequences: reviewers read committed diffs, not staged ones; the run is checkpointed and
    recoverable, which matters because `/resume` does not restore teammates.

- **Persona roster: four phase personas + lens fan-out (Q4)** — `preflight-scout` (read-only:
  has the repo moved under the plan — paths, line numbers, dependency versions, `main`),
  `implementer` (serial, the only writer), `commit-auditor` (read-only, per risky commit: does this
  diff do what the plan's section said and only that), and a final full-diff pass that fans out into
  2–3 independent lenses — correctness, framework idiom, and a guidance-file compliance check
  (CLAUDE.md / AGENTS.md / .github/copilot-instructions.md, which this repo's own rules require
  updating on every codebase change). Built-in `code-review`, `security-review`, and `simplify`
  skills are delegated to rather than reimplemented.
  _(rationale: the phase personas differ in inputs, not tone — plan-vs-repo, diff-vs-plan-section,
  diff-vs-repo-standards — so one shared prompt would be mediocre at three jobs; the end fan-out is
  the design's only genuinely parallel moment.)_
  - Challenged on: five definitions to maintain for an unrun command, and (A) collapses into (C)
    later at near-zero cost → held.
  - Consequences: **the lead must spawn the lens fan-out itself** — teammates cannot spawn teammates
    (no nested teams), so `final-reviewer` cannot fan out. Also, an idle notification carries no
    output, so every reviewer must be instructed to write findings to a file or message the lead
    explicitly.

- **Risk classification by the preflight-scout (Q5)** — the scout, which already reads plan and repo
  before the run, emits a per-commit risk table; `commit-auditor` fires on the commits it marks risky.
  No change to `plan-from-brainstorm.md`, and legacy plans work unchanged.
  _(rationale: a second opinion rather than the planner grading its own homework, and it works on the
  seven existing plans with no edits.)_
  - Challenged on: rejected the mechanical floor, so a single silent misclassification skips review
    entirely — and the repo's own evidence (the `cli.py` deletion, prose-labelled mechanical, is the
    one that broke `main.py` and `pyproject.toml`) says prose labels mislead → user held.
  - Consequences: the scout's risk table is the single gate on per-commit review; mitigation proposed
    (one-line justification per call, table shown to the user before the run) pending.

- **Gate enforcement: prose only, no hooks (Q6)** — the command file instructs the implementer to run
  the gate before committing and to wait for the auditor. No `TaskCompleted` / `TeammateIdle` hooks.
  _(rationale: hooks are session-global config that would fire in every session in this repo, a buggy
  hook script blocks all task completion everywhere, and the docs already list task-status lag as a
  known limitation — a poor place to hang a safety property.)_
  - Challenged on: the most likely failure (implementer reports green without running the gate) stays
    unmitigated, and the Q3b orphan check loses its natural home → mitigation proposed: the implementer
    must record the gate command's actual output tail in a run log so the claim is falsifiable.
  - Consequences: no new settings wiring; everything ships inside the single command file.

- **Run control: one checkpoint after the scout (Q7)** — the run halts once, after `preflight-scout`,
  presenting staleness findings and the risk table for the user's go-ahead; then it runs to the end.
  _(rationale: the scout's output is exactly what would make the user abort, and it arrives before any
  implementation tokens are spent; it also doubles as the visible veto on the Q5 risk table.)_
  - Challenged on: auditor findings are then always self-serviced, including scope disagreements the
    user alone can settle → mitigation proposed: the auditor may raise a halt-severity finding, limited
    to plan contradictions (diff does what the plan never asked, or the plan section is unimplementable
    as written); everything else fix-forwards.
  - Consequences: `/resume` cannot restore teammates, so an interrupted run restarts from the branch
    state, not the team state — the run log is the only recovery record.

- **Persona storage: hybrid (Q8)** — `preflight-scout` and `commit-auditor` (and the end-of-run lenses)
  become `.claude/agents/*.md` definitions so their `tools` allowlist denies `Write`/`Edit` at the
  harness level; the implementer's brief stays inline in the command file.
  _(rationale: the enforced tool allowlist is the only mechanical safety left after hooks and the risk
  floor were dropped, and it only matters for the agents that must not write; the implementer's
  instructions are the command.)_
  - Challenged on: "where is this behaviour defined" becomes "it depends" → mitigation proposed:
    definitions carry only capabilities (`tools`, `model`, one-line role); all task-specific
    instruction lives in the spawn prompt from the command file.
  - Consequences: first `.claude/agents/` in this repo. Definition bodies are *appended* to the default
    system prompt for in-process teammates; `skills` is ignored for teammates, so `code-review` must be
    requested in the spawn prompt, not preloaded.

- **Partial progress: scout reports, user decides (Q9)** — the scout's output includes a per-commit
  "already applied / partially applied / not started" status, and at the Q7 checkpoint the user says
  where the run starts. No auto-resume, no hard refusal on a dirty tree.
  _(rationale: the scout is already diffing plan against repo, the checkpoint already exists, and
  "partially applied" is exactly the state no agent should silently resolve; re-applying or skipping a
  commit fails quietly and expensively.)_
  - Challenged on: the checkpoint now carries three tables, which is real friction on a hand-off
    command → mitigation proposed: the scout emits **one** table, one row per plan commit, with
    status / risk / staleness columns.
  - Consequences: the command works on re-runs, hand-applied prefixes, and post-interrupt resumes —
    the normal case on this repo.

- **End-of-run deliverable: a run log under `docs/cc_logs/` (Q10)** — per-commit gate output, auditor
  findings, final lens findings, and what was fix-forwarded. No automatic push or PR.
  _(rationale: the log is load-bearing for two earlier decisions — it is the falsifiable evidence that
  makes prose-only gate enforcement checkable (Q6) and the only recovery record after an interrupt,
  since `/resume` does not restore teammates. Kept out of `docs/plans/` so process exhaust does not
  accumulate next to the plans.)_
  - Challenged on: a log outside `docs/plans/` loses its link to the plan it came from → naming must
    carry it, e.g. `docs/cc_logs/<plan-filename-stem>_run.md`.
  - Consequences: new directory `docs/cc_logs/`; committed-vs-ignored still open.

- **All six mitigations adopted; `docs/cc_logs/` gitignored (Q11)** — (1) the gate command must pass
  before the commit is made, fix-forward covering reviewer findings only; (2) the scout justifies each
  "mechanical" verdict in one line naming what it checked; (3) the implementer records the gate command
  and its real output tail per commit, and the auditor checks it; (4) the auditor may halt the run for
  plan contradictions only; (5) agent definitions carry `tools`/`model`/one-line role and nothing else;
  (6) the checkpoint is one table, one row per plan commit, status / risk / staleness.
  `docs/cc_logs/` is added to `.gitignore`.
  _(rationale: the mitigations are prose in one file, not infrastructure; the run log's jobs — in-flight
  evidence and interrupt recovery — are both local, so it does not need to survive the branch.)_
  - Challenged on: an ignored log means halt-worthy findings can end up somewhere no reviewer sees →
    consequence: the final report must also surface findings in the terminal, not only in the log.
  - Consequences: `.gitignore` gains `docs/cc_logs/`; the command file grows but stays self-contained.

- **Orphan check dropped (Q12)** — no unconditional per-commit sweep for surviving references to
  deleted symbols. _(rationale: it would be the seventh prose rule in a file already long enough to be
  skimmed, and it is a no-op on most commits, so an instruction that fires everywhere gets learned as
  skippable.)_
  - Challenged on: this is the exact failure the repo has already hit twice, invisible to `make test`
    → user held; recorded as an accepted risk.

## Current frontier (open questions)

_Empty — every branch visited._

## Carried as flags, not decisions

- **Accepted risk: no orphan detection (Q12).** Deletions whose callers survive are caught only by the
  gate command and the risky-commit auditor. `2026Aug28_plan_for_simplification_v1.md` findings #3 and
  #4 (`main.py`'s `from cli import main`, `pyproject.toml`'s `py-modules`) are the class of failure
  this leaves open, and neither is visible to `make test`. Revisit if a run ships a broken build.
- **Accepted risk: no mechanical risk floor (Q5).** A single scout misclassification silently skips
  per-commit review. Mitigated only by the justification line and the user's veto at the checkpoint.
- **Accepted risk: prose-only enforcement (Q6).** No hooks. The run log's gate evidence is the only
  thing making an implementer's "green" claim falsifiable.
- **Pre-run pass framing** recorded as a staleness/progress check rather than a plan-quality
  re-review, on the grounds that `plan-from-brainstorm.md` Step 3 already reviews plan quality. Never
  explicitly confirmed by the user.
- **Agent teams are experimental.** `/resume` does not restore in-process teammates, task status can
  lag, teammates sometimes stop early. An interrupted run restarts from branch state, not team state.
- **Unverified before implementation:** whether `docs/cc_logs/` should also be added to the three
  guidance files' description of the repo layout, per CLAUDE.md's rule that every codebase change
  updates all three.

## Round log

### Round 1 — Q1: Is a team the executor or the escort?
Presented (A) parallel implementers / (B) serial implementer + parallel escort / (C) adaptive.
Lean was (B), strong, on the docs' same-file and sequential-task anti-patterns plus the repo's
actual plan shape. **User answered:** (B) — serial implementer, with a code-review/critic agent
before implementation and again after. **Pushed back on** the pre-implementation critic being
redundant with `plan-from-brainstorm.md`'s three existing reviewers, proposing staleness-check
framing instead → user proceeded; framing carried as a flag.

### Round 2 — Q2: Review granularity, bracket the run or every commit?
Presented (A) bracket run / (B) every commit / (C) bracket run + per-commit only on risky commits.
Lean was (C), weak, because the plan's ordering already encodes risk; against it, no existing plan
carries a machine-readable risk marker. **User answered:** (C). **Pushed back on** the marker being
self-assessed by the same agent that wrote the plan, and on mechanical commits being where silent
breakage actually hides → pending.

### Round 3 — Q3: How work lands, what "reject" means
Presented (A) commit-as-you-go + fix forward / (B) commit-as-you-go + amend / (C) stage-only.
Lean was (B), weak. **User answered:** (A). **Pushed back on** amend-loops having no exit (in favour
of A) and, against A, on fix-forward leaving broken intermediate commits → recorded; refinement
proposed: gate command must pass *before* commit, fix-forward reserved for reviewer findings only.
Also raised the unconditional orphan check (Q3b), unanswered.

### Round 4 — Q4: Persona roster
Presented (A) two thin personas / (B) four phase personas / (C) four + end-of-run lens fan-out.
Lean was (C), weak. **User answered:** (C). **Pushed back on** the docs' no-nested-teams constraint
(the fan-out must be spawned by the lead, not by a reviewer teammate) and on idle notifications not
carrying output → both folded into the decision as consequences.

### Round 5 — Q5: Who decides a commit is risky
Presented (A) planner emits marker / (B) preflight-scout classifies / (C) mechanical derivation /
(D) user marks. Lean was (B) with (C) as a floor, weak. **User answered:** (B), no floor.
**Pushed back on** the single-point-of-failure and on repo evidence that prose "mechanical" labels
misled on the exact commit that broke the build → mitigation proposed, pending.

### Round 6 — Q6: Enforced gates or instructed gates
Presented (A) prose only / (B) `TaskCompleted` hard gate / (C) plus `TeammateIdle`. Lean was (B), weak.
**User answered:** (A). **Pushed back on** the unmitigated "claims green without running" failure and
the orphan check losing its home → mitigation proposed (gate output recorded in a run log), pending.

### Round 7 — Q7: Does the run stop and hand back
Presented (A) fire and forget / (B) one checkpoint after the scout / (C) plus a halt on every auditor
rejection. Lean was (B), strong. **User answered:** (B). **Pushed back on** scope-level findings being
self-serviced → narrow halt-severity escape hatch proposed, pending.

### Round 8 — Q8: Where the personas live
Presented (A) inline / (B) all as `.claude/agents/*.md` / (C) hybrid. Lean was (C), weak.
**User answered:** (C). **Pushed back on** the "it depends" split → convention proposed:
definitions = capabilities, command = behaviour.

### Round 9 — Q9: Plans that are already partly implemented
Presented (A) fresh-run only / (B) scout reports progress, checkpoint decides / (C) auto-resume.
Lean was (B), strong. **User answered:** (B). **Pushed back on** checkpoint weight → single unified
table proposed.

### Round 10 — Q10: What the run leaves behind
Presented (A) terminal report / (B) run log file / (C) run log plus PR. Lean was (B), strong.
**User answered:** (B), located at `docs/cc_logs/`. **Pushed back on** the log losing its link to its
plan → naming convention proposed.

### Round 11 — Q11: Mitigation bundle and log visibility
Presented six mitigations as a set plus the committed-vs-ignored question. Lean was adopt all six,
add the orphan check, and commit the logs. **User answered:** adopt all six, but `.gitignore`
`docs/cc_logs/`. **Pushed back on** the audit trail then being invisible to any reviewer → final
report must also print findings to the terminal. Orphan check left unruled; asked separately as Q12.

### Round 12 — Q12: The orphan check
Presented (A) standing prose instruction / (B) checked-in script / (C) drop. Lean was (A), strong.
**User answered:** (C). **Pushed back on** it being the one demonstrated failure class in this repo's
own plan → user held; moved to accepted risks.

**Session closed:** frontier empty after 12 questions.
