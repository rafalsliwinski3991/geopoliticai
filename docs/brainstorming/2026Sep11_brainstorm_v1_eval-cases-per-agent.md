# Reorganize the manual quality eval cases by agent, add an `e2e` kind, and simplify the runner

**Started:** 2026-09-11
**Status:** Complete
**Mode:** batch (grouped by similarity)
**Classification:** Bounded. One data file, one runner, one test module, one new
prompts module. No component boundary moves.

## Target design

`app/tests/manual_quality/cases.json` becomes an object keyed by agent kind
instead of a flat list of cases tagged with an `agent` field. There are four
kinds, one case each, all happy paths.

| Kind | Case | Input shape | Task | Judges |
|---|---|---|---|---|
| `expert` | niger-coup | `query` | `run_expert` | groundedness, usefulness |
| `orchestrator` | dune-follow-up | `messages` | `run_orchestrator` | route_correct, rewrite_quality |
| `report` | vilnius | `messages` + `resume_actions` | `run_report` | report_fidelity |
| `e2e` | finland-sweden | `turns` | `run_e2e` | route_correct, rewrite_quality, usefulness |

Three kinds drive one branch with controlled input. `e2e` is the only kind that
runs a live multi-turn conversation over one checkpointed thread.

The runner adopts the canonical Phoenix shape: one dataset and one experiment
per kind, with evaluators passed inline to `run_experiment`.
`evaluate_experiment` disappears. Because evaluators bind to a dataset rather
than to an example, the kind owns the judge list, and any second case added to a
kind must share that list.

Reference keys in each case's `output` are prefixed with the judge that reads
them, so the loader can verify a case supplies what its kind's judges need:

| Judge | Reference key |
|---|---|
| route_correct | `route_correct_destination` |
| rewrite_quality | `rewrite_quality_intent` |
| usefulness | `usefulness_required_points` |
| report_fidelity | `report_fidelity_outline` |
| groundedness | none, reads `output.sources` off the run |

The four rubric prompts move to `app/tests/manual_quality/judge_prompts.py`.

## Context verified

- `cases.json` is a flat list of six cases, each carrying an `agent` field. It
  was a dict of agent to a single case until commit 45ef329 (2026-09-10), which
  flattened it so one agent could hold more than one case. The requested shape
  is the natural third form: agent to a list of cases.
- None of the six current cases is a sad path. There is no refusal case, no
  empty-transcript case, and no revise-then-approve case. The reporter case
  sends `[{"action": "approve"}]`.
- The last full run failed two cases. `orchestrator-sweden-follow-up-v1` scored
  `rewrite_quality` 2.0 because classify rewrote "What about Sweden?" as "What
  is the current status of Sweden's NATO membership application?", dropping the
  "why" the preceding turn established. `expert-taiwan-strait-v1` scored
  `groundedness` 2.0 for citing claims to URLs that do not contain them, while
  scoring `usefulness` 5.0 on the same answer.
- `classify` always returns `standalone_query`, including on the `other` branch.
  `RouteDecision` declares it required. A chat-branch orchestrator case
  therefore scores under both `route_correct` and `rewrite_quality` with no
  evaluator changes.
- `has_researched_material` gates the reporter on finding a markdown link to an
  http URL in an assistant turn. A live expert answer always cites URLs, so a
  multi-turn `e2e` report case would clear the gate. The hand-written history in
  the vilnius case also clears it.
- Context7, `/arize-ai/phoenix`: the canonical pattern is one dataset holding
  every example and one `run_experiment` call taking `evaluators=[...]` inline.
  The current runner instead builds one dataset and one experiment per case in a
  Python loop, then calls `evaluate_experiment` separately. The last run produced
  six dataset uploads and six experiment links.
- Context7, `/arize-ai/phoenix`: `input_mapping` accepts a callable as well as a
  dotted path, but there is no mechanism to skip a judge for one example.
  Per-example judge selection is therefore impossible within one experiment.
  This is the fact that forces the kind, not the case, to own the judge list.
- `build_transcript` is exported from `agents.reporter` and renders a whole
  thread within a character budget. It is reusable for the runner's
  `conversation` output field.
- Phoenix's `create_dataset` reads only `input`, `output`, `metadata`, `splits`,
  `span_id`, `id` and `node_id` from an example. The `agent` key the runner
  passes today is silently ignored.
- File composition of `basic_agent_evaluation.py`, 661 lines total: 96 lines of
  rubric prompt text, 58 comment-only lines, 85 blank. Largest functions are
  `run_experiment_case` (65), `main` (62), `validate_evaluations` (55),
  `run_reporter_thread` (50), `build_expert_evaluators` (36).
- `CLAUDE.md` describes this script as advisory and never documents the case
  schema, so it needs no update.

## Settled decisions

- **`e2e` means a live multi-turn conversation on one thread** (Q1, option A).
  _(rationale: `orchestrator` and `reporter` cases already invoke the whole
  graph, so a new kind must test something genuinely uncovered, and no case can
  currently express a turn that depends on what a previous turn really
  produced.)_
  - Challenged on: multi-turn mixes two agents' quality into one score, and
    will not catch a delivery-layer bug that only the HTTP and SSE path shows
    → held.
  - Consequence: rejects testing through the API layer, which would have needed
    Postgres and uvicorn inside the eval run.

- **One case per kind** (Q2, option A). _(rationale: the suite is advisory,
  gates no merge, and exists to give a fast signal rather than coverage.)_
  - Challenged on: the two cases most likely to be dropped are the only two that
    ever found a defect, which turns the suite into a green light that cannot go
    red → held, with the defects to be recorded before deletion.
  - Consequence: run cost falls from six live cases to four, with three live
    searches instead of six.

- **`e2e` replaces rather than duplicates** (Q3, reading 2). _(rationale: adding
  `e2e` alongside unchanged kinds would run Finland and Vilnius content twice
  each and make the suite bigger, not smaller.)_
  - Later partially revisited by Q13: the reporter branch returns as the
    `report` kind with controlled input.

- **`e2e` finland is two turns** (Q4, option B). Turn one asks why Finland
  joined NATO, turn two asks "What about Sweden?". _(rationale: a single-turn
  `e2e` case would be the existing orchestrator task under a new label.)_
  - Challenged on: it doubles the case's cost and reintroduces the coreference
    case just voted away → held.
  - Consequence: the sweden rewrite defect stays in the suite, now measured
    against a live answer rather than a hand-written one.

- **The orchestrator case is a two-turn non-political exchange** (Q5). Turn one
  asks who wrote Dune, the assistant answers Frank Herbert, turn two asks "When
  did he die?". _(rationale: a bare greeting proves the `other` route but leaves
  `rewrite_quality` nothing to grade.)_
  - No objection raised.

- **Reference keys are prefixed with the judge that reads them** (Q7, option A).
  `must_address` becomes `usefulness_required_points`, and the other three
  follow. _(rationale: renaming one of four leaves a convention that half-holds,
  which reads worse than either extreme.)_
  - Challenged on: `route_correct_destination` is uglier than `destination`, and
    the prefix repeats what the kind table already states → held.
  - The user's first suggestion was `usefulness_expected_output`; changed to
    `usefulness_required_points` because the judge is told to treat the list as
    a coverage checklist and never as evidence, and "expected output" invites
    the next person to paste a gold answer into it. The usefulness prompt
    already labels the field "Required points".

- **The `expert` kind keeps niger-coup** (Q8). _(rationale: it is the only
  choice where no two cases in the suite share a subject.)_
  - Challenged on: taiwan is the only expert case that ever found anything, so
    niger leaves the kind represented by a case that has only ever passed
    → held.

- **One dataset and one experiment per kind** (Q9, option B). Evaluators pass
  inline to `run_experiment`; `evaluate_experiment` is deleted. _(rationale:
  this is the canonical Phoenix shape, and the per-case loop it replaces was
  only needed to support per-case judges.)_
  - Challenged on: at today's inventory it yields four experiments either way,
    so it buys nothing until a kind holds several cases of the same shape
    → held.
  - Consequence: **overturns Q6.** The per-case `evaluators` field is deleted
    before it is ever written. The kind owns the judge list.

- **Judges belong to the kind, not the case** (Q6, superseded). Q6 originally
  settled on option B, a per-case `evaluators` list. Q9's answer makes that
  impossible, since Phoenix evaluators bind to a dataset. Recorded here so the
  reversal is visible rather than silent.

- **The rubric prompts move to `judge_prompts.py`** (Q10, option A, renamed from
  `rubrics.py` at the user's request). _(rationale: 96 lines is the largest
  block in the file, and every agent in this repo already keeps prompts in a
  sibling module.)_
  - Challenged on: a judge is its prompt plus its mapping, so splitting them
    makes a rubric change two file opens → held.

- **Comments are not touched** (Q11, option A). _(rationale: the user chose to
  keep even the stale and misplaced ones rather than audit a judgement call in
  the diff.)_
  - Narrow exception confirmed: a comment attached to code the change deletes
    goes with that code. The comment explaining why `"reporter"` is in
    `KNOWN_AGENTS` cannot survive the removal of that name.
  - Consequence: the stale "commit 5a" comment and the misplaced threshold
    comment above `logger` stay where they are unless their code goes.

- **Four kinds: `expert`, `orchestrator`, `report`, `e2e`** (Q12 and Q13).
  _(rationale: three kinds drive one branch with controlled input, and `e2e` is
  the single kind that runs live, which makes the four names mean one coherent
  thing.)_

- **The `report` kind uses hand-written history** (Q13, reading 2). It keeps
  today's `messages` plus `resume_actions` input and today's task, renamed
  `run_report`. _(rationale: the score then moves only when the reporter's code
  or prompt changes, and the case still walks the entire graph because classify
  routes it and the subgraph pauses at the gate.)_
  - Challenged on: it leaves nothing testing the reporter against research the
    expert actually produced, which is the real production path → held.
  - Consequence: no live search for this case. Its `report_fidelity_outline` can
    name specific summit facts, because turn one is fixed.

- **The `report` kind drops `route_correct`.** Only the report branch pauses at
  a gate and the task already fails loudly when the turn did not pause, so that
  judge could never score anything but 1.0.
  - Raised by the assistant during the final design, not put to the user as a
    round. Flagged here for confirmation during implementation.

- **Task outputs converge on shared field names**, so each judge needs one field
  mapping rather than one per kind. Every task returns `answer`. The expert adds
  `standalone_query` and `sources`. The other three add `conversation`, and the
  two routing kinds add `destination`. `conversation` reuses
  `agents.reporter.build_transcript`.

- **Phoenix receives only `input`, `output` and `metadata`.** The runner's own
  `id` stays runner-side. _(rationale: Phoenix half-reads the extra keys today
  and silently drops the rest.)_

## Design tree

- Reorganize `cases.json` by agent — **SETTLED**
  - Nesting shape: object keyed by kind, value a list — **SETTLED**
  - `agent` field inside each case — **SETTLED**, deleted, the key replaces it
  - Reference key naming — **SETTLED** (Q7A, judge-prefixed)
- Add an `e2e` kind — **SETTLED**
  - What it runs: multi-turn live vs API layer vs relabel — **SETTLED** (Q1A)
  - Whether it adds or replaces — **SETTLED** (Q3 reading 2, then Q13)
  - Turn count for finland — **SETTLED** (Q4B, two turns)
  - Input script format — **SETTLED**, ordered `turns` list of `query` or `resume`
- Fewer cases, happy paths only — **SETTLED** (Q2A, one per kind)
  - Which expert case survives — **SETTLED** (Q8, niger)
  - Chat case content — **SETTLED** (Q5, Dune coreference)
- Who owns the judge list — **SETTLED** (Q6 then Q9, the kind owns it)
  - Phoenix experiment granularity — **SETTLED** (Q9B, per kind)
  - How `report_fidelity` survives — **SETTLED** (Q12 and Q13, its own kind)
- Simplify the runner — **SETTLED**
  - Prompts location — **SETTLED** (Q10A, `judge_prompts.py`)
  - Comment handling — **SETTLED** (Q11A, untouched)
  - Function decomposition — **SETTLED**, registry replaces three builders
- Testing through the HTTP and SSE layer — **PRUNED** at Q1. Needs Postgres and
  uvicorn inside the eval run, and produces pass/fail assertions that sit oddly
  beside a 1-to-5 rubric. Belongs in pytest, not here.
- Adding sad-path cases (refusal, empty transcript, revise-then-approve)
  — **PRUNED** at Q2. Explicitly out of scope: happy paths only for now.

## Current frontier (open questions)

Empty. The session closed with every branch visited.

## Carried as flags, not decisions

- **The taiwan citation defect leaves the suite.** `expert-taiwan-strait-v1`
  found real citation misattribution and scored `groundedness` 2.0. Record the
  defect somewhere durable before the case is deleted. The sweden rewrite defect
  survives, inside `e2e` finland turn two.
- **Nothing tests the expert feeding the reporter.** Accepted at Q13. The
  production path where a report is written from a live expert answer is
  unwatched by the suite.
- **A kind owns its judges.** A second case added to any kind must share that
  kind's judge list, or it needs a kind of its own. This constraint is what the
  whole shape rests on and deserves a comment at `build_kinds()`.
- **Nothing stops a case's kind declaring `groundedness` when its task returns
  no sources.** It fails at field-mapping time with a clear error rather than at
  load time. Worth a loader check only if it actually happens.
- **`JUDGED_SCORE_THRESHOLD` stays 3.0** and remains provisional. No historical
  score distribution exists to justify it.
- **The judge timeout is unaddressed.** `PHOENIX_TIMEOUT_SECONDS` is 180, and a
  groundedness prompt carrying seven full article texts to a free OpenRouter
  endpoint exceeded it last run. Phoenix cancelled, printed a traceback,
  requeued, and recovered. Out of scope here.
- **Paywalled domains are unaddressed.** Reuters, AP, Axios and France24 return
  401 or 403 on every run. Each case still lands five to seven sources out of
  ten candidates. Out of scope here.
- **Run cost estimate is unverified.** Three live searches expected, one for the
  expert and two for `e2e` finland, with `orchestrator` and `report` making
  none. Projected four to five minutes against roughly eight today.
- **Line count estimate is unverified.** Roughly 480 lines in the runner plus a
  100-line `judge_prompts.py`, against 661 today.
- **`test_live_results_use_phoenix_native_output` must change.** It asserts
  exactly one `evaluate_experiment` call carrying `print_summary=True`. After
  this change there will be zero. The assertion moves onto `run_experiment`.

## Round log

### Round 1 — Q1: what an `e2e` case actually runs; Q2: which cases survive
Asked whether `e2e` meant a multi-turn conversation on one thread, a run through
the HTTP and SSE layer, or a relabelling of the existing full-graph cases.
Showed that `orchestrator` and `reporter` cases already walk the entire graph.
Lean was A (multi-turn), weak, with the counter-case that A cannot catch a
delivery-layer bug and mixes two agents into one score.
Separately asked how many cases survive, noting all six are already happy paths
so the cut is about volume, not kind. Lean was one per agent, weak, with the
counter-case that the two droppable cases are the only two that found anything.
**User answered:** Q1 A, Q2 A. Also resolved the overlap unprompted: `e2e` takes
the finland and vilnius cases through the entire graph, and `orchestrator`
narrows to classify plus chat. **Pushed back on** multi-turn flakiness, since a
thin search day would drag a report score down for a non-code reason → held.

### Round 2 — Q3: does `e2e` add or replace; Q4: is `e2e` finland multi-turn
Verified first that `has_researched_material` accepts a live expert answer, so a
multi-turn report case clears the gate.
Q3 offered reading 1 (e2e adds, six cases, finland and vilnius each run twice)
against reading 2 (e2e replaces the `reporter` kind, four cases, nothing runs
twice). Lean was reading 2, strong, countered by the loss of an isolated
reporter signal.
Q4 offered a single-turn `e2e` finland against a two-turn version ending in the
Sweden coreference. Lean was B, weak, countered by doubled cost and the return
of a case just voted away.
**User answered:** Q3 reading 2, Q4 B, and chose a two-turn non-political
exchange for the chat case. **Pushed back on** the vilnius reference, which was
written against hand-written facts and would fail against a live search → the
user later resolved this by moving the report case back to controlled input in
Q13.

### Round 3 — Q6: which judges run on which case
Showed that `e2e` finland ends in an answer with sources while `e2e` vilnius
ends in a report with none, so one judge list per kind could not cover both.
Offered fixing judges per kind and judging only what both share, a per-case
`evaluators` list, or inferring judges from which reference keys a case supplies.
Lean was the explicit list, weak, countered by it being the most schema for the
least code.
**User asked** what `must_address` is. Answered with the taiwan case's real
value, the usefulness prompt's "Required points" binding, and the judge's 5.0
verdict quoting both points. **User answered:** option B, with a request to
rename `must_address` to something judge-named.

### Round 4 — Q7: rename all four reference keys; Q8: which expert case
**Pushed back on** `usefulness_expected_output`, which reads like a gold answer
and fights the prompt's instruction to treat the list as a checklist rather than
evidence. Proposed `usefulness_required_points`, matching the prompt's own
wording. Q7 offered prefixing all four keys against renaming only the unclear
one; lean A, weak, countered by the prefixes repeating the kind table. Q8
offered niger, finland or taiwan for the `expert` kind; lean niger, weak,
countered by taiwan being the only expert case that ever found a defect.
**User answered:** Q7 A, Q8 niger.

### Round 5 — the design, then a scope addition
Presented a full design. **User added scope:** make the runner simpler and more
readable, and check Phoenix patterns through Context7. Reclassified aloud as
still Bounded but larger.

### Round 6 — Q9: Phoenix experiment granularity; Q10: prompts; Q11: comments
Context7 showed the canonical pattern is one dataset with many examples and
evaluators inline, and that no mechanism exists to skip a judge for one example.
Reported that the per-case loop was therefore load-bearing for Q6, and that Q9
and Q6 could not both hold. Measured the file: 96 lines of prompt, 58 comment,
85 blank. Lean on Q9 was A (keep the loop), strong. Lean on Q10 was A (move the
prompts), strong. Lean on Q11 was B (cut stale comments), weak.
**User answered:** Q9 B, Q10 A, and said Q11 was not understood.

### Round 7 — Q11 re-posed; Q12: how `report_fidelity` survives
Re-posed Q11 with three real comments from the file: one recording a measured
langgraph behaviour, one describing a finished commit-staging plan, one
annotating the wrong line. Q12 reported that Q9B deletes `report_fidelity`
entirely, since the two `e2e` cases must share judges and Q3 had removed the
reporter kind. Offered accepting that against giving vilnius its own kind. Lean
was its own kind, strong, countered by four experiments matching the per-case
loop the user had just voted away.
**User answered:** Q11 A, and asked for Python pseudocode of both Q12 options.

### Round 8 — Q12 shown as code
Wrote both options as the case JSON plus the kind table plus the shared loop,
showing that only the table differs and that two kinds can share one task
function. **User answered:** four kinds named `expert`, `orchestrator`, `report`
and `e2e`.

### Round 9 — Q13: what `report` means
Flagged that `report` read two ways and showed the vilnius case body under each:
a live multi-turn run, or the reporter branch with hand-written history. Noted
that the controlled-input version still walks the entire graph, since classify
routes it and the gate pauses. Lean was reading 2, weak, countered by leaving
the expert-to-reporter handoff untested.
**User answered:** reading 2.

### Round 10 — final design approved
Presented the complete design, including one unprompted change: the `report`
kind drops `route_correct`, which could only ever score 1.0 given the task
already fails when the turn did not pause. **User approved**, renaming
`rubrics.py` to `judge_prompts.py`, and asked for the implementation plan.
