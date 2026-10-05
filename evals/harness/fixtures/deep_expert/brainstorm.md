# Deep expert agent: an opt-in, iterative, self-graded research path, plus its evals

**Started:** 2026-09-28
**Status:** Complete
**Mode:** batch (similar questions per round, default)

## Target design

A new `agents/deep_expert/` agent built with `deepagents.create_deep_agent` (gpt-5-mini),
with custom `search` and `fetch` tools over the shared `search.py` boundary and the expert's
`EXPERT_SOURCES` policy, `write_todos` planning, the virtual FS, the built-in `task`
subagent, and `RubricMiddleware` (gpt-4o-mini grader, `DEEP_ANSWER_RUBRIC`,
`RUBRIC_MAX_ITERATIONS`). The orchestrator node `deep_expert` invokes it on
`standalone_query` and returns one `AIMessage`; it emits `progress` events (planning,
searches, reading, "Revising (k/N)") and delivers the final answer once as a `notice`.
The classifier routes to `"deep"` only after an explicit request for depth, and keeps
same-topic follow-ups deep; a new topic or "quick/short" resets. A deep turn spends N quota
units from both counters and is refused (429) when fewer remain. Hard caps on searches,
grader rounds, and wall time (<600 s) are hard errors; `max_iterations_reached` ships the last
draft; `grader_error`/`failed`, search outages, and answers with no allow-listed citation are
hard errors. Evals: deep routing rows in the orchestrator eval, a new `deep_expert` eval on
recorded sources reusing expert judges plus a depth judge against a live expert baseline, and
one e2e sticky-mode conversation.

## Approved design sections

**§1 Architecture** — `START -> classify -> {expert | deep_expert | chat | reporter} -> END`.
`deep_expert` node invokes a `create_deep_agent` graph inside the node (like `expert`), not via
`add_node` of the child graph.

**§2 Components** — `agents/deep_expert/` (`graph.py` builds the agent; `tools.py` `search`/
`fetch` over `search.py` + `EXPERT_SOURCES` with cap counting; `prompts.py` system prompt +
`DEEP_ANSWER_RUBRIC`; `config.py` model settings + caps). Orchestrator: `"deep"` in
`Destination`, classifier prompt rules, node + edge, `nodes/deep_expert.py`. `api.py`: `"deep"`
in `RESEARCH_DESTINATIONS`, charge N. `db/web/sql.py`: `cost` param on both quota upserts (no
schema change). `config.py`: `DEEP_RESEARCH_TURN_COST`. `pyproject.toml`: `deepagents>=0.7.19`.
`CLAUDE.md` updated.

**§3 Data flow** — classify sets `destination="deep"` → API quota check (N units, 429 if short,
site counter first) → node runs agent, tools emit `progress`, grader callback emits
"Revising (k/N)" → final answer as one `notice` (within `MAX_ANSWER_CHARS`) → node returns an
`AIMessage` so follow-ups see it in history.

**§4 Error handling** — search outage: hard error (502/503 as expert); search/time cap hit:
hard error; `max_iterations_reached`: ship last draft + log; `grader_error`/`failed`: hard
error (node reads `_rubric_status`); no allow-listed citation: hard error; insufficient quota:
429.

**§5 Testing & evals** — unit: tools with fake search (allow-list, cap counting), node
`_rubric_status` branches + progress events, `tests/unit_tests/agents/deep_expert/test_graph.py`,
orchestrator routes to `deep`, quota SQL with cost, API charges N / 429 when short. Evals: 7
routing rows in `orchestrator.json`; new `evals/deep_expert.py`, `judges/deep_expert.py`,
`datasets/deep_expert.json` (recorded sources, expert's 3 judges + depth judge vs. live
expert baseline); one e2e sticky-mode conversation.

## Context verified

- The pasted `deep_expert` docstring describes code that does **not** exist in the repo;
  `agentic_backend/src/agents/` holds only `expert/`, `orchestrator/`, `reporter/`, and no
  `deep` string appears under `src/`.
- Orchestrator today: `Destination = Literal["geopolitical", "other", "report"]`
  (`src/agents/orchestrator/state.py`); routing map in `src/agents/orchestrator/graph.py`;
  classifier prompt `CLASSIFY_SYSTEM_PROMPT` in `orchestrator/prompts.py`.
- `api.py`: `ANSWER_NODES = {"answer", "chat", "write"}`, `RESEARCH_DESTINATIONS =
  {"geopolitical", "report"}`, `MAX_ANSWER_CHARS = 50_000`; the `notice` custom event already
  flows through the `MAX_ANSWER_CHARS` accounting (api.py ~471, ~634–652).
- Quota: `DAILY_RESEARCH_TURNS = 20` per user, `DAILY_RESEARCH_TURNS_ALL_USERS = 500` site-wide
  (`src/config.py`). A research turn is counted once regardless of its cost.
- Expert: one fixed pass, three Brave batches, `gpt-4o-mini` answer at temperature 0
  (`agents/expert/config.py`).
- Lockfile (`agentic_backend/uv.lock`) already has `langchain-core 1.6.5`,
  `langchain-openai 1.1.9`, `langgraph 1.2.12`, `openai 1.109.1`. The docstring's claim that
  the required versions are "newer than `pyproject.toml` pins" is only about the *floors* in
  `pyproject.toml` (`langchain-core>=1.2.22`); the lock already satisfies `deepagents`.
- PyPI `deepagents` latest is **0.7.19**. Its hard requirements: `langchain>=1.4.2`,
  `langchain-core>=1.6.4`, **`langchain-anthropic>=1.7.4`**, **`langchain-google-genai>=4.4.0`**,
  `langsmith>=0.14.0`, `packaging`, `wcmatch`. So adopting it pulls two provider SDKs this
  OpenAI-only project does not use.
- `deepagents.middleware.rubric.RubricMiddleware` exists in 0.7.19. It activates only when a
  `rubric` is passed on invocation state. On `failed`, `max_iterations_reached`, or
  **`grader_error` it does not raise** — it leaves the last draft as the final message and
  records `_rubric_status`. "Grader crash is a hard error" therefore requires the node to read
  `_rubric_status` and raise itself.
- Evals: one script per eval (`evals/expert.py`, `orchestrator.py`, `reporter.py`, `e2e.py`).
  `evals/helpers/graph.py::recorded_sources` patches `search_allowlisted`/`fetch_sources`
  **in `agents.expert.nodes.search_and_fetch`** and returns the same recorded sources for any
  query. The orchestrator eval stops before `expert`/`reporter` with `interrupt_before`.
  `orchestrator.json` has 4 examples (other, 2× geopolitical, report); `expert.json` has 1.

## Settled decisions

- **Build approach** — a real `deepagents` agent (planning, iterative search/fetch, virtual FS,
  `task` subagent, `RubricMiddleware` grader loop) under `agents/deep_expert/`
  _(rationale: user wants genuinely iterative research, not a bigger fixed pipeline)_
  - Challenged on: extra `langchain-anthropic`/`langchain-google-genai` SDKs and unbounded
    per-turn cost → held; SDKs accepted.
  - Consequences: adds `deepagents>=0.7.19` (+ transitive provider SDKs) to `agentic_backend`;
    requires hard caps (next decision).
- **Hard caps per deep turn** — yes: bounded searches, grader rounds, and wall time; exceeding a
  cap is a hard error, not a degraded answer _(rationale: a deep turn still costs one quota
  unit; caps are the only spend ceiling)_
  - Challenged on: caps too low make deep barely deeper than expert → accepted; exact numbers
    are tuning (see flags).
  - **Revised at plan review (2026-09-28, user decision):** the search cap is a soft stop — search 16
    returns "no searches left" without calling Brave — because a hard error killed turns when parallel
    `task` subagents overshot the shared budget. Only the wall-time cap remains a hard error.
- **Routing trigger** — composite: the classifier decides, but only when the user *explicitly*
  asks for a deep / in-depth / advanced / thorough answer, in any phrasing. The classifier
  interprets paraphrases; it never chooses deep for a plain question on its own judgement of
  complexity _(rationale: users control spend; no keyword matching)_
  - Challenged on: pure classifier judgement (original answer B) reversed the opening ask and
    let classifier drift drive spend → revised to this composite.
  - Consequences: `CLASSIFY_SYSTEM_PROMPT` gains an explicit-request rule; orchestrator eval
    needs positive paraphrase rows and negative rows ("deep state", complex-but-unasked).
- **Waiting experience** — progress lines via the existing `progress` SSE event (planning,
  each search query, reading N sources, "Revising (k/N)"); grader criticism is never shown;
  answer delivered once at the end as `notice` _(rationale: minutes of silence reads as broken)_
  - Challenged on: extra node wiring/tests vs. zero-change spinner → no objection beyond that;
    held. The delivery layer already forwards custom events regardless of namespace.
- **Grader never satisfied** — ship the last draft when `_rubric_status ==
  "max_iterations_reached"`; log it. `grader_error`/`failed` remain hard errors
  _(rationale: running out of revision budget is normal termination, not a failure)_
  - Challenged on: contradicts the docstring's "never a degraded answer" → user holds A; the
    docstring line is amended to cover crashes only. No objection pushed further.
- **Follow-ups inherit deep, same topic only** — after an explicit deep request, follow-ups
  that refer back to that topic ("and Poland?") stay deep; a new topic, or an explicit
  "quick/short/brief" request, returns to the normal expert. This refines Q2: an explicit
  request is needed to *enter* deep mode on a topic _(rationale: natural follow-ups without
  letting one request make the whole thread expensive)_
  - Challenged on: "same topic" is fuzzy; the classifier will misjudge both ways → held.
  - Consequences: classifier sees history (it already does); eval needs sticky and reset rows.
- **Quota cost** — a deep turn spends N units (not 1) from both the per-user and, pending Q8,
  the site-wide counter _(rationale: a deep turn costs 10–30× an expert turn; sticky mode makes
  deep turns easy to accumulate)_
  - Consequences: `INCREMENT_QUOTA`/`INCREMENT_SITE_QUOTA` take a cost parameter
    (`used + cost`, `WHERE used + cost <= limit`); `api.py` passes N when destination is deep;
    the UI's remaining count reflects it; schema-guard tests unchanged (no schema change).
- **Eval coverage** — (1) orchestrator eval gains deep routing rows (explicit, paraphrase,
  "deep state" negative, complex-but-unasked negative, same-topic follow-up, topic change
  reset, "quick summary" reset) and `interrupt_before` gains `deep_expert`; (2) new
  `evals/deep_expert.py` + `judges/deep_expert.py` + `datasets/deep_expert.json`, reusing the
  expert's URL-provenance / answer-agreement / faithfulness judges and recording search count,
  grader rounds, final `_rubric_status`; (3) a new **depth judge** scoring whether the deep
  answer covers more angles than a baseline expert answer; (4) one e2e conversation covering
  explicit deep → sticky follow-up → reset _(rationale: without a depth judge nothing shows the
  10–30× spend buys anything)_
  - Challenged on: judge prompt + tests + slow e2e cost → held; baseline source is Q9.
- **Deep eval fake search** — every search returns the example's whole recorded pool (same
  pattern as `recorded_sources`, patched in the deep expert's tool module) _(rationale:
  eval measures synthesis and the grader loop; live search quality is checked by hand)_
  - Challenged: no objection beyond the stated one (search strategy is invisible to evals);
    consequence: the depth judge measures synthesis breadth over identical sources, not
    research breadth.
- **Insufficient balance** — refuse with 429 "A deep analysis needs N research turns; you have
  M left today."; no fallback to the expert. Site counter is charged N too _(rationale: one
  error message, no second routing path)_
  - Challenged on: user gets nothing when a normal answer was affordable → held.
- **Depth judge baseline** — the eval runs the real expert on the same recorded sources per
  example and the judge compares the two live answers _(rationale: a stored baseline goes
  stale on any expert prompt change)_
  - Challenged on: two stochastic outputs make the score noisier → held.
- **Models** — deep agent `gpt-5-mini` (temperature 1.0, per the reporter's documented
  gpt-5 constraint); grader `gpt-4o-mini` (temperature 0.0). Both `LLMSettings` constants in
  `agents/deep_expert/config.py` _(rationale: stronger model where planning happens, cheap
  grader; two-way door, the depth judge shows whether the grader is too lenient)_
  - Challenged on: a weaker grader may pass drafts a stronger one would reject → held.

## Design tree

- Build approach — SETTLED: deepagents (Q1)
  - Dependency footprint — SETTLED: accept provider SDKs
  - Hard caps — SETTLED: yes, hard error on breach; numbers are a flag
  - Grader `max_iterations_reached` outcome — SETTLED: ship last draft, log (Q7)
  - Grader `grader_error` — SETTLED by docstring: hard error (node reads `_rubric_status`)
- Routing trigger — SETTLED: classifier, explicit request required (Q2)
  - Follow-up turns inherit deep? — SETTLED: same topic only; new topic or "quick" resets (Q6/Q6b)
  - Classifier examples & eval rows — follows from Q2 + Q6
- Cost & quota — SETTLED: N units per deep turn (Q3)
  - Not enough balance — SETTLED: refuse 429; site counter charged N (Q8)
- What the user sees while it runs — SETTLED: progress lines, no grader criticism (Q4)
- Evals — SETTLED: routing rows + deep_expert eval + depth judge + one e2e (Q5a)
  - Fake search — SETTLED: whole recorded pool per query (Q5b)
  - Depth judge baseline — SETTLED: live expert run on same sources (Q9)
- Models — SETTLED: agent gpt-5-mini, grader gpt-4o-mini (Q10)

## Current frontier (open questions)

_(empty)_
- **Q4 — Waiting experience**: silent until done vs. progress lines (searching X, revising 2/3).


## Carried as flags, not decisions

- **Cap numbers** (searches, grader rounds `RUBRIC_MAX_ITERATIONS`, wall time) — tuning in
  `agents/deep_expert/config.py`; proposed start 15 searches / 3 grader rounds / 300 s. Decide
  at plan time.

## Round log

### Round 1 — Q1: Build approach; Q2: What triggers deep mode
Q1 lean was A (weak): deepagents library. **User answered:** A.
Q2 lean was A (strong): explicit request only. **User answered:** B — classifier judges need for depth.
Pushback posed in round 2 (both still untested): Q1 → extra provider SDKs + unbounded per-turn
cost; Q2 → contradicts the opening ask ("only if user asks about deep") and, combined with Q1A,
spends unpredictable cost on turns the user never opted into.

### Round 2 — challenge Q1/Q2; Q4: waiting experience
**User answered:** Q1 "yes" (SDKs + caps held). Q2 revised to composite: classifier decides,
but the user must explicitly ask for a deep/advanced answer. Q4 not answered → carried.

### Round 3 — Q3 quota, Q4 (re-ask), Q6 follow-up inheritance, Q7 max-iterations outcome
**User answered:** Q4 B (lean). Q6 B — follow-ups inherit deep (lean was A, strong). Q7 A (lean).
Q3 unanswered. Q6B contradicts settled Q2 ("nothing goes deep without an explicit ask") →
Q2 wording reopened as Q6b.

### Round 4 — Q6b: how inherited deep ends; Q3 (re-ask)
**User answered:** Q6b A (lean, strong) — same topic only. Q3 B (lean was A, weak) — N units.
Verified: quota is charged in `api.py` on the `counted` custom event after classify, site
counter first; both upserts hard-code `+ 1`.

### Round 5 — Q8 insufficient balance; Q5a eval coverage; Q5b fake search
**User answered:** Q5a B (lean was A, weak) — add depth judge + e2e. Q5b A (lean). Q8 unanswered.

### Round 6 — Q8 (re-ask); Q9 depth baseline; Q10 models
**User answered:** Q8 A (lean). Q9 A (lean). Q10 B (lean was C, weak).
Verified: reporter documents that gpt-5* accepts only temperature 1.0 and that nginx/browser
abort at 600 s.

### Round 7 — approaches comparison + design sections
Approaches: (1) separate `agents/deep_expert/` package invoked from its own orchestrator node
— recommended; (2) deep mode inside `agents/expert/` — rejected (breaks one-agent-per-dir,
makes the expert's fixed three-batch rule conditional); (3) hand-rolled LangGraph loop —
rejected by Q1A.
**User approved** approach 1 and design sections §1–§5 by asking to save and proceed to
`rs-plan-from-brainstorm`.
