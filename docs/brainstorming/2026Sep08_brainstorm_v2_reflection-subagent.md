# A Reflection-pattern self-correction pass for the expert agent: draft, critique, revise

*(Opened as "a new subagent using the Reflection design pattern." Q8 settled that there is **no new
agent package** — the pattern lands as three new nodes inside the existing `expert` graph. The
filename keeps the original slug, per the one-slug-per-session rule.)*

**Started:** 2026-09-08
**Status:** Complete — frontier empty, awaiting user approval of the artifact
**Mode:** batch (similar questions per round, default)

*(Session v1 of the same day, `2026Sep08_brainstorm_v1_rag-subagent.md`, grilled a different
topic — a RAG subagent — and was abandoned after Round 1 was posed. This file is independent.)*

## Target design

A **grounding self-check** on the expert's answer path. Not a loop and not a separate agent:
three new nodes inside `app/src/agents/expert/`, run unconditionally on every geopolitical question.

```text
START -> search_and_fetch -> draft -> critique -+-(supported)----> emit draft
                                                |
                                                \-(problems)----> revise -> emit
```

| step | model | visible? | ~time |
|---|---|---|---|
| `search_and_fetch` | — | progress label | ~12s |
| `draft` | `gpt-4o-mini` | **no** — full text held in state, never forwarded | ~10s |
| `critique` | **`gpt-5-mini`** | no | ~15s |
| `revise` *(only if problems found)* | `gpt-4o-mini` | no | ~10s |
| emit | — | yes — text reaches the browser as `token` frames | — |

- **What is checked:** grounding. Does every claim in the draft trace to one of the fetched sources?
  Not style, not completeness, not retrieval quality.
- **Who judges:** `gpt-5-mini`, deliberately not the `gpt-4o-mini` that wrote the draft. Returns a
  structured verdict through `llm.ainvoke_structured`, so the critique is inspectable and loggable.
- **Who rewrites:** `gpt-4o-mini`, the original writer, working from the critic's problem list.
- **How many passes:** exactly one. The revision is never re-checked.
- **What the user sees:** nothing until the answer is final. New progress labels narrate the wait.
  Common case ~37s and 2 model calls; corrected case ~47s and 3.
- **When the critic breaks:** the unchecked draft ships anyway rather than failing the request.

**The critic's contract.** `critique` returns a structured object through `llm.ainvoke_structured`
(`method="json_schema", strict=True`), carrying the offending **spans**, not prose descriptions:

```json
{"supported": false,
 "problems": [{"span": "blocked it again in February 2024",
               "why": "No fetched source states a February 2024 block."}]}
```

The spans are the contract between the two nodes: `revise` may change **only** those spans, plus
sentences that directly reference a removed one. Everything else is reproduced verbatim, asserted in
a test over text normalised with `" ".join(text.split())`.

**Getting text to the browser.** Both output paths carry text that no model is streaming live, which
`api.py` cannot currently forward — it only forwards `AIMessage` chunks from nodes named in
`ANSWER_NODES`. This design **depends on the reporter agent's v3 emit mechanism**
(`StreamWriter` / `stream_mode="custom"`) already being merged. See "Preconditions" below.
Recommendation on the record: use **one** emit mechanism for both the replay and the revise path;
two mechanisms reintroduce the duplicate-`AIMessage` problem that `api.py`'s `streamed_nodes` guard
exists to solve.

**When the checker fails.** A `LLMInvocationError` or schema failure in `critique` is caught: the
draft ships unchanged, the user is told nothing, and a fixed greppable `WARNING` plus a Phoenix span
attribute record it. A failure in `draft` still propagates as 502, unchanged.

**How it is tested.** Offline, like everything else in this repo — no test calls a live model.
`pytest` stubs the verdict and asserts three paths: problems present → `revise` runs and only the
flagged spans changed; clean verdict → the draft is replayed with no second model call; `critique`
raises → the draft ships and the warning is logged. The existing node-set and edge-set assertions in
`test_expert_graph.py` are updated to pin the new shape. Judge *quality* is advisory only, via
planted-error cases added to `tests/manual_quality/cases.json` **in the same commit as the feature**.

**Preconditions to verify before implementation**

1. `api.py` on the base commit emits custom events — i.e. the reporter merged at **v3 level**, not
   the v1-level `2026Sep05-reporter-agent` branch, which still has
   `stream_mode=["updates", "messages"]` and no `StreamWriter`. If absent, a narrow emit path for
   the replay case must be built and the estimate grows.
2. One live `gpt-5-mini` call confirming: structured output via `json_schema`/`strict=True` works,
   `max_completion_tokens` covers reasoning plus visible tokens, and the ~400k window figure holds.
   The repo has never made a `gpt-5*` call.

Timings are estimates from configured timeouts plus assumed generation speed. **Nothing here has
been measured against a live call**, and the repo has never invoked a `gpt-5*` model.

## Approaches considered for the overall shape

The tree tested individual decisions; this records that the overall shape was chosen, not inherited.

| | what it is | why not chosen |
|---|---|---|
| **1. Grounding self-check** *(chosen)* | `draft` → `critique` → `revise`, one pass, always on | — |
| **2. Just upgrade the writer** | Delete the loop; `answer` runs on `gpt-5-mini` with the same sources | **One call instead of three**, and no wait doubling. Rejected because the critique is a *separable, inspectable* artifact: a logged verdict makes the catch rate measurable, which a better writer never does. **This remains the fallback** if Q2's falsifier fires. |
| **3. Corrective retrieval** | Critic judges the *sources*, not the draft; re-searches when they are thin | Fixes bad inputs rather than second-guessing outputs, and would have been cheaper in tokens. Rejected in Q1: the failure that damages this product is an unsupported sentence in a cited answer, not a thin source list. Extra Brave batches at 10s each also make the tail latency worse than the chosen shape. |

## Context verified

Facts established from the repo and from Context7, not from the user.

### The central collision: this app streams, reflection rewrites

- `api.py:_astream_answer` runs `graph.astream(..., stream_mode=["updates", "messages"],
  subgraphs=True)` and forwards every `AIMessage` chunk whose
  `metadata["langgraph_node"]` is in `ANSWER_NODES = frozenset({"answer", "chat"})`
  as an SSE `{"type": "token"}` frame. The browser renders those as they arrive.
- Deduplication is by node name: `streamed_nodes` records which nodes have already emitted
  chunks, so a node's *completed* `AIMessage` is dropped once its chunks were forwarded
  (`api.py`, the `message.__class__ is AIMessage and node in streamed_nodes` guard).
  **A second generating node with a different name would stream as a second block of text**,
  appended to the first, not replacing it.
- `_generate` accumulates every forwarded chunk into `parts` and finally emits
  `{"type": "result", "output": "".join(parts)}`. There is no frame type that means
  "discard what I sent you and start over."
- Ceiling: `MAX_ANSWER_CHARS = 50_000`, enforced by truncation while still draining upstream.

### What one answer costs today (the baseline a loop multiplies)

- `expert` = `START -> search_and_fetch -> answer -> END` (`agents/expert/graph.py`).
- Retrieval: 3 parallel Brave batches, `BRAVE_TIMEOUT_SECONDS = 10.0`, then up to
  `fetch_candidates=10` concurrent page fetches at `FETCH_TIMEOUT_SECONDS = 5.0`,
  `FETCH_CONCURRENCY = 8`, keeping `keep_sources=8` (`search.py`, `agents/expert/config.py`).
- Generation: exactly one streamed call, `ANSWER_LLM_SETTINGS = LLMSettings(model="gpt-4o-mini",
  temperature=0.0, timeout_seconds=60.0, max_output_tokens=16_384)`.
- The prompt carries up to 8 sources at `max_source_chars=20_000` each — so a critique call that
  re-reads the sources re-sends **up to 160k characters** of source text per iteration.

### Guidance this would contradict, and must therefore update

- CLAUDE.md: *"The expert makes exactly three Brave batches, extracts allow-listed pages with
  trafilatura, and makes **one streamed plain-text model call**."*
- CLAUDE.md: *"Expert search, source, and model failures are hard errors; **do not add degraded
  fallbacks**."* A reflection loop that gives up after N rounds and ships the last draft is,
  by that sentence's logic, a degraded fallback — unless it is defined as success instead.

### The agent-boundary pattern a new agent must follow

- A subagent is a separately compiled graph **invoked inside an orchestrator node**, never passed
  to `add_node`, because the state schemas share no key (`agents/orchestrator/nodes/expert.py`;
  CLAUDE.md states this as a rule).
- No `config` is passed to the child `ainvoke`; LangGraph propagates the parent run through
  contextvars, which is what produces the `expert:<task id>` stream namespace.
- Shared modules (`config.py`, `models.py`, `search.py`, `llm.py`, `tracing.py`, `api.py`) never
  import agents. `llm.py` exposes exactly three call shapes: `astream_messages`, `astream_text`,
  and `ainvoke_structured` (`with_structured_output(schema, method="json_schema", strict=True)`,
  tagged `TAG_NOSTREAM` so it never reaches a `stream_mode="messages"` consumer).
- Errors are `PipelineError` subclasses carrying a `status` ClassVar: 503 `SearchUnavailableError`,
  422 `NoSourcesError`, 502 `LLMInvocationError` (`models.py`).
- Per-node LLM knobs are hardcoded `LLMSettings` in the agent's own `config.py`, never env-read.

### `gpt-5-mini` through this repo's `llm.py` — verified in the installed package

Read directly from the vendored source, not inherited from the reporter plan
(`langchain_openai/chat_models/base.py`, `validate_temperature`, a `@model_validator(mode="before")`,
`langchain-openai==0.3.35`):

```python
if model.startswith("gpt-5") and "chat" not in model:
    temperature = values.get("temperature")
    if temperature is not None and temperature != 1:
        # For gpt-5 (non-chat), only temperature=1 is supported
        # So we remove any non-defaults
        values.pop("temperature", None)
```

- **`LLMSettings(temperature=0.0)` is silently discarded for `gpt-5-mini`.** No warning, no error.
  The call reaches the API with no temperature at all, i.e. the provider default of 1.0.
  `llm._build_client` passes `temperature=settings.temperature` unconditionally, so this happens
  transparently to every call site. `gpt-5-chat-latest` and `gpt-4o-mini` keep 0.0.
- **Consequence: the judge is non-deterministic.** Identical draft + identical sources can yield a
  pass on one run and a fail on the next. That makes the loop's iteration count non-deterministic
  too, and it is the central testing problem for this agent (Q6).
- An `LLMSettings` for the critic should therefore state `temperature=1.0`, so the code says what
  actually reaches the API.

Corroborating figures from `docs/plans/2026Sep04_plan_reporter-agent_v3.md` §"Unverified provider
claims" — **treated as second-hand, not re-verified here**: `gpt-5-mini` context window ~400k tokens,
max output 128,000 tokens, `max_completion_tokens` bounds reasoning *and* visible tokens, and
`with_structured_output(..., method="json_schema", strict=True)` is supported.
The repo has **never** made a live `gpt-5*` call: every `LLMSettings` in `app/src/` is `gpt-4o-mini`,
and `tests/manual_quality/basic_agent_evaluation.py` pins `JUDGE_MODEL = "gpt-4o-mini-2024-07-18"`.

Sizing note: 8 sources x 20,000 chars is ~160k characters, roughly 40k tokens — comfortably inside
a ~400k window. Context length is **not** a constraint on the critique call; latency and cost are.

### Installed versions (from `app/uv.lock`, verified 2026-09-08)

`langgraph` **1.0.1**, `langgraph-checkpoint` 3.0.1, `langgraph-checkpoint-postgres` 3.0.5,
`langchain-core` 3.0.2, `langchain-openai` 0.3.83, `openai` 2.5.2, `langgraph-prebuilt` 1.0.1.

### Context7 — LangGraph (`/websites/langchain_oss_python_langgraph`, verified 2026-09-08)

- The loop idiom is the plain Graph API: a counter in the state schema plus
  `add_conditional_edges` returning either the node to loop back to or `END`. The documented
  shape is literally `class AgentState(TypedDict): ... retry_count: int` with
  `def should_continue(state): if state["retry_count"] > 3: return "end"`.
- The agentic-RAG example cycles `generate -> grade -> rewrite_question -> generate` with
  `workflow.add_edge("rewrite_question", "generate_query_or_respond")` — a critique node routing
  back to a generating node is a first-class documented pattern, not a workaround.
- LangGraph also ships `RetryPolicy(max_attempts=..., retry_on=...)` and node `error_handler`
  returning `Command(update=..., goto=...)` — but these are for *node failures* (exceptions),
  not for "the output was judged poor." They are not the reflection mechanism.
- **No prebuilt reflection/critique helper exists.** The loop is hand-written nodes.

### In-flight work this collides with

- `app/src/agents/reporter/` exists as **empty `consts/` and `nodes/` directories, untracked**
  (`git ls-files app/src/agents/reporter` returns nothing).
- `docs/plans/2026Sep04_plan_reporter-agent_v3.md` is a full-tier plan against base `31583ef`;
  per its §0 two unmerged branches carry implementations (`2026Sep05-reporter-agent`, 11 commits,
  complete but v1-level; `2026Sep06-reporter-agent-codex`, 5 commits, Commits 1-3 only).
- The reporter adds a **third** destination (`report`) to
  `Destination = Literal["geopolitical", "other"]` in `agents/orchestrator/state.py`, and changes
  `api.py` to emit progress via `StreamWriter`/`stream_mode="custom"`. A reflection agent routed
  by the classifier would be the **fourth** destination and would touch the same three files.

### Test layout, and the fact that **nothing in this repo calls a live model**

- `app/tests/unit_tests/` (incl. `agents/`, `test_api.py`, `test_llm.py`),
  `app/tests/integration_tests/` (`test_expert_graph.py`, `test_orchestrator_graph.py`),
  `app/tests/manual_quality/` (`basic_agent_evaluation.py` + `cases.json`).
- `make test` is bare `python -m pytest $(TEST_FILE)`; `make integration_tests` is
  `python -m pytest tests/integration_tests`. **Neither hits a provider.**
  `test_expert_graph.py` imports `llm` at module scope specifically to monkeypatch it, and otherwise
  asserts graph shape — e.g. `set(compiled.get_graph().nodes) - {"__start__","__end__"} ==
  {"search_and_fetch","answer"}` and the exact edge set. **Both of those assertions break** the
  moment `draft`/`critique`/`revise` are added, and are the natural place to pin the new shape.
- `basic_agent_evaluation.py` is the only live-model code, pins
  `JUDGE_MODEL = "gpt-4o-mini-2024-07-18"`, and is advisory — outside pytest and CI.
- Consequence for Q6: "test the judge" cannot mean a live assertion without inventing a category of
  test this repo has never had.

## Settled decisions

- **Q1 — The critic checks grounding, and `gpt-5-mini` is the judge** — the critic re-reads the
  sources the expert already fetched and flags claims none of them support; the judging model is
  `gpt-5-mini`, not the `gpt-4o-mini` that wrote the draft.
  _(rationale: the product premise is cited answers from a 28-domain allow-list, so the failure that
  actually damages it is a fluent, confident, unsupported sentence.)_
  - Challenged on: my Round 1 objection was self-grading — the same model at the same temperature
    rubber-stamping its own output. **The user's answer pre-empted it**: a different, stronger judge
    is exactly the falsifier I named. Re-challenged instead on whether the loop should exist at all
    if `gpt-5-mini` is trusted to judge — see Round 2.
  - Consequences: the critique call must receive the source text, so the critic can only live
    somewhere that has `state["sources"]` — this constrains Q2. Adds a second model family to the
    app. Requires `temperature=1.0` in the critic's `LLMSettings` (see Context verified), and makes
    the judge non-deterministic, which opens Q6.

- **Q3 — The loop is invisible; only the final answer streams** — no draft text reaches the browser;
  new progress labels narrate the extra wait.
  _(rationale: nothing on screen should ever be wrong, and there is no SSE frame type meaning
  "discard what I sent you".)_
  - Challenged on: time-to-first-word. See Round 2 — the objection is that A also forecloses the
    only cheap latency escape hatch.
  - Consequences: no new SSE frame type, no frontend replacement logic. New progress labels only.
    `ANSWER_NODES` in `api.py` must **not** include the draft node, or the draft would stream.
    The revise node is the only node whose `AIMessage` chunks may be forwarded.

- **Q2 — Every geopolitical answer is checked** — no gate, no opt-in, unconditional on the expert path.
  _(rationale: a gate is a second thing to build, tune and be wrong in; "sometimes verified" is a much
  weaker claim than "slower, but always verified".)_
  - Challenged on: it is a permanent ~25s tax on every answer to catch an **unmeasured** error rate,
    and the cheapest gate isn't a classifier but `len(state["sources"]) < 4` — one line, no model call.
    → held.
  - Consequences: this is **not** a fourth classifier destination, so `Destination` and
    `CLASSIFY_SYSTEM_PROMPT` are untouched and the reporter's `classify` collision evaporates.
    Median latency roughly doubles. **Open falsifier, carried as a flag:** 10 hand-run questions
    changing materially fewer than 1 in 10 times would make always-on indefensible.

- **Q4 — Exactly one correction pass; not a loop** — `draft -> critique -> revise -> ship`.
  _(rationale: one pass captures most of the benefit at a third of the tail latency, with no counter,
  no conditional loop-back, and no exhaustion policy.)_
  - Challenged on: the shipped text has then been checked by **nothing** — `gpt-5-mini` reads the
    draft, `gpt-4o-mini` writes a different text, and that text ships unread. → held; Q7's problem
    list plus Q10's span constraint are the mitigation instead of a second iteration.
  - Consequences: Q5 (exhaustion policy) never arises. Call count is fixed at 2 or 3, which largely
    contains the non-determinism opened by the `gpt-5-mini` temperature finding.

- **Q5 — A passing draft is replayed, not regenerated** — the finished text already in state is
  pushed to the browser; no second generation on the common path.
  _(rationale: paying a full generation to "fix" an answer with nothing wrong with it is the most
  expensive possible no-op, and would make the good case slower than the bad case.)_
  - Challenged on: this is a typewriter animation over a finished string, and the honest cheap
    version is a single `result` frame with no `token` frames at all — the fake typing is paid for
    purely by perceived latency and consistency with the `chat` branch. → held.
  - Consequences: **forces a new emit path in `api.py`.** Today it forwards only `AIMessage` chunks
    from nodes named in `ANSWER_NODES`; stored text has no route out. This is the same plumbing the
    reporter plan v3 is rewriting to `StreamWriter`/`stream_mode="custom"` — see Q-seq.

- **Q7 — The critic reports; the original writer rewrites** — `gpt-5-mini` returns the problems it
  found, `gpt-4o-mini` produces the final text from that feedback.
  _(rationale: user's own framing — "the first model rewrites but with instructions/feedback from
  the checking model". Keeps the verdict inspectable and keeps the untested `gpt-5*` path off the
  user-visible output.)_
  - Challenged on: `gpt-4o-mini` rewriting ~800 words from a note commonly removes the flagged claim
    *and* silently rephrases others, one of which returns unsupported — same model, same weakness,
    nothing downstream checks it. → held; remedy offered (critic returns offending **spans**,
    reviser edits only those) is **not yet answered** and is now Q10.
  - Consequences: 3 model calls on the corrected path. The verdict is a structured object via
    `ainvoke_structured`, so catch-rate is measurable from logs — which is what would settle Q2's
    open falsifier.

- **Q8 — No new agent package; three nodes inside `expert`** — `draft`, `critique`, `revise` join
  `search_and_fetch` in `app/src/agents/expert/`.
  _(rationale: a `reviewer` agent would be an interface with one implementation and one caller,
  always run, whose boundary's only job is handing over the same 8 sources the expert already holds.)_
  - Challenged on: **this is a drift from the opening ask** — the session began "add a new subagent"
    and lands with no new agent at all; and it falsifies three separate CLAUDE.md sentences at once.
    → held.
  - Consequences: `agents/expert/nodes/answer.py` becomes `draft.py`; `agents/expert/state.py` gains
    the draft text, the verdict, and the final text; `agents/expert/config.py` gains two `LLMSettings`.
    CLAUDE.md's expert paragraph needs three edits (see flags).

- **Q9 — If the checker fails, the unchecked draft ships** — a `gpt-5-mini` timeout or schema failure
  does not kill the request.
  _(rationale: the existing hard-error rule was written for the case where a model failure means
  there is no answer; here there is an answer and only the audit failed.)_
  - Challenged on: the guarantee silently becomes "checked unless it wasn't", and nobody can tell
    which answer they got. → held, accepted as a live risk; whether the degradation is **silent or
    visible** is still open and is now Q11.
  - Consequences: contradicts CLAUDE.md's "do not add degraded fallbacks" for the expert; that
    sentence must be scoped to search/source failures explicitly. `LLMInvocationError` from
    `critique` is caught; from `draft` it still propagates as 502.

- **Q10 — The reviser may only change the flagged spans** — everything the critic did not flag is
  reproduced verbatim.
  _(rationale: turns "we hope it only fixed what we asked" into something a unit test can assert,
  which is the mitigation Q4's single pass depends on.)_
  - Challenged on: a flagged span is often load-bearing — remove "and blocked it again in February
    2024" and a following "That second veto prompted..." is orphaned, yielding accurate but broken
    prose; and asking `gpt-4o-mini` to reproduce 800 words verbatim invites drift that makes the
    assertion flaky until it is loosened into meaninglessness. → held, with two remedies on the
    record: the reviser may also adjust sentences that **directly reference** a removed span, and the
    verbatim assertion runs over text normalised with `" ".join(text.split())`, the idiom already
    used in `build_initial_pipeline_state` and `classify`.
  - Consequences: the critic's verdict schema must carry the offending **spans**, not just prose
    descriptions. That schema is the contract between the two nodes.

- **Q11 — The skipped check is silent to the user and loud in the logs** — a `WARNING` plus a Phoenix
  span attribute; no banner in the answer.
  _(rationale: Phoenix is already wired, so the rate costs nothing to record, and it is the number
  that decides whether this needs escalating; a warning users cannot interpret reads as
  "this answer is wrong".)_
  - Challenged on: a log nobody reads is indistinguishable from silence, and there is no alerting —
    a checker failing 30% of the time would go unnoticed. → held, with the remedy that the skip rate
    must be **retrievable on demand**: a fixed greppable log message, a Phoenix span attribute, and a
    skip count surfaced in `tests/manual_quality/basic_agent_evaluation.py`.
  - Consequences: no frontend change and no new SSE frame for this case.

- **Q6 — Offline wiring tests; judge quality stays advisory** — `pytest` stubs the verdict and
  asserts the three paths; real `gpt-5-mini` behaviour is exercised only by hand.
  _(rationale: a live pass/fail gate on a model pinned at temperature 1.0 is flaky by construction
  and would be skipped within a month; this matches how `basic_agent_evaluation.py` already handles
  non-deterministic quality questions.)_
  - Challenged on: under A every test passes even if the critique prompt is empty — you test the
    plumbing and never the feature. → held, with the requirement that planted-error cases land in
    `cases.json` **in the same commit as the feature**, not as a follow-up.
  - Consequences: `test_expert_graph.py`'s node-set and edge-set assertions must be updated.
    No API keys in CI. No new test category.

- **Q-seq — The reporter lands first; this is built on top of it** — the user's stated premise is
  that the reporter will already be merged when this is implemented.
  _(rationale: the reporter's v3 plan already builds the custom-event emit path this design needs,
  so building a narrow one first would be knowingly throwaway work.)_
  - Challenged on: "in place" is not sufficient — it must be in place **at v3 level**. The complete
    branch `2026Sep05-reporter-agent` is v1-level, still `stream_mode=["updates","messages"]` with no
    `StreamWriter`; merging that one leaves the dependency unmet and silently reverts this to
    Option B. → held, with the dependency recorded as **Precondition 1**, to be checked rather than
    assumed.
  - Consequences: no `classify` collision (Q2 already removed the fourth-destination risk), but a
    hard ordering dependency on `api.py`. This design must not start before that check passes.

## Design tree

- **Q1 — What the critic checks** SETTLED — grounding, judged by `gpt-5-mini`
  - **Q7 — Critique reported, not applied** SETTLED — critic reports, `gpt-4o-mini` rewrites
    - **Q10 — Surgical spans or free rewrite?** SETTLED — spans only, with reference-repair allowed
  - **Q8 — Nodes in `expert`, not a new agent** SETTLED
    - **Q-seq — Sequencing against the unmerged reporter work** SETTLED — reporter lands first;
      this design depends on its v3 emit mechanism
  - **Q6 — Testing a judge that cannot be pinned to temperature 0** SETTLED — offline wiring tests;
    judge quality advisory only
- **Q2 — Every geopolitical answer is checked** SETTLED — unconditional
  - Gate design (`len(sources) < 4`, etc.) PRUNED by Q2, retained as the falsifier in flags
- **Q3 — Invisible loop; only the final answer streams** SETTLED
  - **Q5 — A passing draft is replayed** SETTLED
    - Whether `revise` also replays rather than streaming live — PRUNED to implementation.
      Recommendation on the record: **one emit mechanism for both paths**, since Q5 forces a replay
      path to exist anyway and two mechanisms reintroduce the duplicate-`AIMessage` problem
      `api.py`'s `streamed_nodes` guard exists to solve.
  - Progress label wording — PRUNED to implementation
- **Q4 — Exactly one pass** SETTLED
  - Exhaustion policy — PRUNED, cannot arise with a fixed single pass
- **Q9 — Unchecked draft ships if the checker fails** SETTLED
  - **Q11 — Is that degradation visible to the user or silent?** SETTLED — silent to the user, logged

## Current frontier (open questions)

*(Empty. Every live branch was visited; nothing was silently assumed.)*

## Carried as flags, not decisions

- CLAUDE.md's "one streamed plain-text model call" and "no degraded fallbacks" sentences will need
  rewriting or explicit scoping, whichever way Q2 lands.
- The critic's `LLMSettings` must say `temperature=1.0`, not `0.0`, so the code matches what reaches
  the API. Verified against installed `langchain-openai==0.3.35`; re-check if that version moves.
- `gpt-5-mini`'s window, max output, `max_completion_tokens` semantics, and structured-output support
  are **second-hand from the reporter plan and unverified by a live call**. One real call before
  implementation would settle all four.
- The repo has never invoked a `gpt-5*` model. This design would be the first, so the first
  integration test that hits it is also a provider-compatibility test.
- **Q2's open falsifier (accepted risk).** Nobody has measured how often the critic catches a real
  grounding error. Always-on was chosen without that number. The structured verdict from Q7 makes it
  loggable; if materially fewer than 1 in 10 answers change, revisit the one-line
  `len(state["sources"]) < 4` gate.
- **Three CLAUDE.md edits, as one deliberate line item, not incidental cleanup:**
  1. the expert's graph diagram gains `draft -> critique -> revise`;
  2. "makes exactly one streamed plain-text model call" becomes two or three, and names the models;
  3. "do not add degraded fallbacks" is scoped to search and source failures, since Q9B adds
     precisely such a fallback for critique failures.
- All latency figures in this document are **estimates**, not measurements. `search_and_fetch`'s ~12s
  derives from configured timeouts; every generation figure is assumed.
- **Precondition 1 (blocking):** confirm `api.py` on the base commit emits custom events, i.e. the
  reporter merged at v3 level. If not, a narrow emit path must be built and the estimate grows.
- **Precondition 2:** one live `gpt-5-mini` call to confirm structured output, `max_completion_tokens`
  semantics, and the window figure — all currently second-hand.
- **Planted-error cases ship with the feature**, not after it. Without them nothing exercises the
  grounding check at all.
- **The fallback if Q2's falsifier fires** is Approach 2 (run `answer` on `gpt-5-mini`, delete the
  loop), not a gate bolted onto this design.

## Round log

### Round 1 — Q1: what the critic checks; Q3: what the user sees while it runs
Asked both as independent siblings. **Q1** offered: (A) grounding — flag claims no fetched source
supports; (B) completeness/viewpoint coverage, read from the draft alone and much cheaper;
(C) critique the *retrieval* and re-search instead, looping back to `search_and_fetch`.
Lean was A (weak), with the stated falsifier: "it's `gpt-4o-mini` grading `gpt-4o-mini` — run 10
questions by hand, and fewer than 2 genuine catches makes A theatre."
**User answered: A, with `gpt-5-mini` as the judge.** That answer *is* the falsifier's remedy —
a different, stronger model — so the original objection does not survive contact.
**Pushed back instead on** whether the loop earns its place at all if `gpt-5-mini` is trusted to
judge: one grounded `gpt-5-mini` generation may beat draft-critique-revise at lower cost and
latency. → *(see Round 2 for the outcome)*

**Q3** offered: (A) silence for longer, then one clean streamed answer behind new progress labels;
(B) the draft streams and is then visibly replaced, needing a new SSE frame type meaning "discard".
Lean was A (weak). Against it: time-to-first-word roughly doubles on a path already ~15s slow.
**User answered: A.**
**Pushed back on** the fact that A also forecloses the cheap latency escape hatch — you cannot
"ship the draft if the loop runs long" when the draft was never sent, and CLAUDE.md forbids that
fallback anyway. → *(see Round 2 for the outcome)*

### Round 2 — Q2: who pays the latency; Q4: how many correction passes
**Q2** offered (A) check every geopolitical answer, (B) a cheap gate, (C) user opt-in.
Lean was A (weak). **User answered: A.** **Pushed back on** committing every user to ~25s for an
unmeasured error rate when the cheapest gate is one line of existing state → **held**.
**Q4** offered (A) exactly one pass, (B) loop to a cap of 2-3. Lean was A (strong), stated openly as
contradicting the word "loop" in the original request. **User answered: A.**
**Pushed back on** the fact that the shipped text is then checked by nothing at all — the critic
reads a draft that is subsequently replaced → **held**, with Q7/Q10 as the mitigation.

### Round 3 — Q5: what happens when the draft passes; Q7: does the critic report or fix
**Q5** offered (A) replay the draft already in memory, (B) run the rewrite anyway.
Lean was A (strong). **User answered: A.** **Pushed back on** it being a typewriter animation over a
finished string, where one `result` frame would be less code → **held**.
**Q7** offered (A) critic reports and `gpt-4o-mini` rewrites, (B) `gpt-5-mini` returns the corrected
answer itself. Lean was B (weak). **User answered: A**, in their own words — "the first model
rewrites but with instructions/feedback from checking model". **Pushed back on** the weak model
rewriting 800 words from a note and introducing fresh unsupported claims, and offered the
span-constraint remedy → **held**; the remedy itself went unanswered and became Q10.

### Round 4 — Q8: separate agent or nodes in the expert; Q9: what if the checker fails
**Q8** offered (A) three nodes inside `expert`, (B) a `reviewer` agent package.
Lean was A (weak). **User answered: A.** **Pushed back on** the drift — the session opened asking for
a subagent and lands with none — and on three CLAUDE.md sentences becoming false at once → **held**.
**Q9** offered (A) 502 the request, (B) ship the unchecked draft. Lean was B (weak).
**User answered: B.** **Pushed back on** the guarantee silently becoming conditional with no way for
a user to tell which answer they got → **held as an accepted risk**; visibility split out as Q11.

### Round 5 — Q10: surgical spans or free rewrite; Q11: silent or visible degradation
**Q10** offered (A) rewrite the whole answer guided by the problem list, (B) change only the flagged
spans and reproduce the rest verbatim. Lean was B (weak). **User answered: B.**
**Pushed back on** load-bearing spans orphaning following sentences, and on verbatim reproduction
being the thing weak models are worst at → **held**, with reference-repair and normalised comparison
added as remedies.
**Q11** offered (A) silent to the user, `WARNING` + Phoenix span attribute, (B) a line in the answer
saying the check did not run. Lean was A (weak). **User answered: A.**
**Pushed back on** having no alerting, so a persistently failing checker would go unnoticed →
**held**, with the requirement that the skip rate be retrievable on demand.

### Round 6 — Q6: how the judge is tested; Q-seq: order against the reporter
**Q6** offered (A) offline wiring tests with judge quality advisory, (B) a live suite scoring the
judge on planted errors. Lean was A (strong). **User answered: A.**
**Pushed back on** A testing the plumbing and never the feature — every test passes with an empty
critique prompt → **held**, with planted cases required in the same commit.
**Q-seq** was first posed in codebase terms and the user said it needed explaining more simply —
**my failure, not theirs**. Re-posed with the same two options, rebuilt around the one function that
moves text to the browser and the fact that both features need the same new capability from it.
**User answered:** "the reporter will be in place when we will implement this" — i.e. Option A.
**Pushed back on** the premise: the *complete* reporter branch is v1-level with no `StreamWriter`,
so merging it would leave the dependency unmet → **held**, recorded as Precondition 1.
