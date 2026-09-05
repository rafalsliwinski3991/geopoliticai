# Human-in-the-loop report agent: a third orchestrator branch that drafts a downloadable Markdown report behind an approval gate

**Started:** 2026-09-04
**Status:** Complete — frontier empty, awaiting user approval of the artifact
**Mode:** batch (similar questions per round, default)

## Target design

A fourth branch on the orchestrator, implemented as a new agent package `app/src/agents/reporter/`,
that turns a conversation into a downloadable Markdown report behind a human approval gate.

**Graph**

```text
START -> classify -> expert   -> END
                  \-> chat     -> END
                  \-> reporter -> END
```

`reporter` is a compiled subgraph, **invoked inside an orchestrator node** (never handed to
`add_node`), exactly as `expert` is — its state is disjoint from the orchestrator's:

```text
START -> outline -> gate -(revise)-> outline
                          \-(approve)-> write -> END
                          \-(cancel)--> END
```

**Behaviour**

1. The classifier gains a third destination, `report`. Plain-language requests ("write me a report on
   the eastern flank") route there. No button, no slash command.
2. `outline` reads **the entire thread** — every message, not a window — and proposes a short section
   list. It performs **no search or fetch of its own**; the material is the conversation's existing
   cited expert answers.
3. If the thread contains no researched material, the branch **refuses and explains**, telling the user
   to ask about the topic first.
4. `gate` calls `interrupt()` with the outline. The run pauses; the browser shows it and waits.
5. The user approves, cancels, or types free-text revision instructions. A revision redraws the outline
   and pauses again.
6. A revision requesting material the thread does not contain is **refused at the gate**, which
   re-shows the unchanged outline.
7. `write` produces the report with `gpt-5-mini`, preserving the `[anchor](URL)` citations already
   present in the source answers.
8. The report streams into the chat and carries **Download .md** and **Copy** buttons, both purely
   client-side.

**Delivery**

`POST /api/run_pipeline/stream` accepts either `{query, thread_id}` or `{resume, thread_id}`.
A new SSE frame type carries the pause and its outline to the browser.

When text arrives for a **paused** thread, a small three-way intent classifier sorts it into
*revise / new question / cancel*. A new question **cancels the pending report** and is answered
normally; the report request is dropped. This classifier's prompt and `LLMSettings` live in
`agents/reporter/`, and the delivery layer calls it before choosing between `Command(resume=...)` and a
fresh state input — the decision determines which of the two the graph receives, so it cannot live
inside the graph.

## Context verified

Read from the checked-out tree at `1ee8dba` on 2026-09-04:

- **Orchestrator shape** — `app/src/agents/orchestrator/graph.py`: `START -> classify -> {expert|chat} -> END`.
  `build_graph(checkpointer)` takes the saver as an argument and never builds one.
- **Routing type** — `app/src/agents/orchestrator/state.py:20`: `Destination = Literal["geopolitical", "other"]`.
  `RouteDecision` is a Pydantic model used with `with_structured_output(strict=True)`; both fields
  required, no defaults. `OrchestratorState` = `{messages (add_messages), destination?, standalone_query?}`.
- **Classifier model** — `gpt-4o-mini`, `temperature=0.0`, 20s timeout, 512 output tokens
  (`orchestrator/config.py`). Prompt is hand-written in `orchestrator/prompts.py`.
  **There is no routing-accuracy measurement anywhere in the repo** — `tests/manual_quality/`
  scores answer quality, not which branch was chosen.
- **History window** — `HISTORY_WINDOW_TURNS = 10`, `HISTORY_WINDOW_MESSAGES = 20`
  (`orchestrator/config.py:32`). Both `classify` and `chat` slice `state["messages"][-20:]`.
- **Expert boundary** — `orchestrator/nodes/expert.py` invokes the compiled expert *inside* the node
  (`await expert_graph.ainvoke(...)`) rather than via `add_node`, because the expert's
  `{query, sources, answer}` state shares no key with the orchestrator's. Documented as a deliberate
  LangGraph 1.0.1 workaround: `add_node` on the child would silently discard its result.
  The expert is compiled with **no checkpointer** (`expert/graph.py:24`).
- **Expert output is already cited Markdown** — `ANSWER_SYSTEM_PROMPT` rule 1 requires every factual
  sentence to carry an inline `[anchor](URL)` link copied character-for-character from the source block.
- **Structured sources do not escape the expert** — `orchestrator/nodes/expert.py:38` returns only
  `{"messages": [AIMessage(answer)]}`. The `list[Source]` (title, url, full article text) is discarded.
  Anything downstream sees cited answer *text*, never source objects.
- **Expert sizing** — `ANSWER_LLM_SETTINGS`: `gpt-4o-mini`, `max_output_tokens=16_384` (~65k chars);
  `RETRIEVAL`: 10 fetch candidates, 8 kept sources (`expert/config.py`).
- **Derived context risk** — 20 messages of expert answers at up to ~65k chars each can exceed
  `gpt-4o-mini`'s 128k-token input context. Reading "the whole conversation" is not free.
- **Expert fails hard** — no usable sources raises `NoSourcesError` (422); there is no degraded output
  path (`expert/nodes/answer.py:33`).
- **API contract** — `app/src/api.py`: exactly one streaming endpoint,
  `POST /api/run_pipeline/stream`, body `RunPipelineRequest {query: str<=2000, thread_id: str<=100 matching ^[A-Za-z0-9_-]+$}`.
  SSE frame types emitted: `progress`, `token`, `result`, `error`. **No pause/resume frame exists.**
  Driven by `graph.astream(state, config, stream_mode=["updates","messages"], subgraphs=True)`.
  The `updates` handler skips any event with a non-empty namespace (`api.py`: `if namespace or not isinstance(data, dict): continue`).
  `ANSWER_NODES = {"answer", "chat"}` gates which nodes' AI messages are forwarded.
  Output capped at `MAX_ANSWER_CHARS = 50_000`. Rate limit 20 req / 60s per resolved client id.
- **Persistence** — `AsyncPostgresSaver` over an `AsyncConnectionPool` built in `lifespan`;
  `DATABASE_URL` required at API startup. `build_graph()` without a checkpointer stays valid for
  `make test` and `langgraph dev`.
- **Frontend** — `frontend/index.html`, 620 lines, single file. Alpine.js 3, `marked` + `DOMPurify`
  (`ALLOWED_URI_REGEXP: /^https?:\/\//i`), thread id in `localStorage` under
  `politicalagent.thread_id`, minted with `crypto.randomUUID`, reset by **New chat**.
  10-minute client-side `AbortController` timeout. Handles exactly the four SSE frame types above.
- **The frontend never rehydrates thread history.** `init()` sets
  `messages = [{role: "bot", text: I18N.welcome}]` unconditionally. A page reload shows an empty chat
  even though the thread is still checkpointed server-side, and there is no endpoint to read it back.
- **No Content-Security-Policy header** is set in `frontend/nginx.conf` or `nginx.local.conf`, so a
  client-side `Blob` + `<a download>` save is unobstructed. `proxy_read_timeout 600s` matches the
  frontend's 10-minute abort.
- **Versions (app/uv.lock)** — langgraph 1.0.1, langgraph-checkpoint 3.0.1,
  langgraph-checkpoint-postgres 3.0.5 (pinned `<3.1`: 3.1 needs checkpoint>=4.1, langgraph 1.0.1 needs <4.0),
  langchain-core 1.3.1, psycopg 3.3.5.
- **Tests** — `app/tests/unit_tests/` mirrors `src/` (`agents/orchestrator/test_{classify,chat,expert,state}.py`),
  plus `test_api.py`, `test_frontend_security.py`, `test_frontend_ux.py` (the frontend is tested by
  asserting on the HTML/JS source text). `app/tests/integration_tests/test_orchestrator_graph.py`.

Verified via Context7 (`/websites/langchain_oss_python_langgraph`, 2026-09-04):

- **Resume contract** — `Command(resume=<any JSON-serializable value>)` is passed as the *input* to
  `invoke`/`stream`/`stream_events` on the **same `thread_id`**. It is the only `Command` form intended
  as graph input; `update`/`goto`/`graph` are for returning from nodes.
- **Node re-execution on resume** — "the node restarts from the beginning of where `interrupt` was
  called." Anything executed *before* the `interrupt()` call in the same node runs **again** on resume.
  Hard constraint on where the interrupt is placed.
- **Interrupt payload** — the value passed to `interrupt(...)` is what the client sees; the value passed
  to `Command(resume=...)` becomes `interrupt()`'s return value inside the node.

Verified against the installed `langgraph==1.0.1` in `app/.venv` (resolves the earlier FLAG):

- `langgraph.types.interrupt(value)` (`types.py:396`) and `langgraph.types.Command` (`types.py:342`)
  both exist in this version.
- **Interrupts surface on the `updates` stream mode**, as `{"__interrupt__": (Interrupt(...), ...)}`
  — `pregel/_loop.py:834` and `:897`; `INTERRUPT = sys.intern("__interrupt__")` in
  `_internal/_constants.py:9`. This repo already consumes `stream_mode=["updates", ...]`, and an
  interrupt raised in a top-level orchestrator node carries an empty namespace, so it survives
  `api.py`'s existing namespace filter.

Verified empirically against the installed `langgraph==1.0.1` (probe script, `InMemorySaver`, 2026-09-04):

| # | Situation | Observed behaviour |
|---|---|---|
| 1 | Node calls `interrupt()` | `{"__interrupt__": (...)}` emitted on `updates`, **empty namespace** — survives `api.py`'s existing `if namespace: continue` filter |
| 2 | `Command(resume=...)` on a paused thread | Node **re-runs from its first line** (probe logged `gate-entered` twice), then continues. Confirms the doc claim |
| 3 | `Command(resume=...)` on a thread that is **not** paused | **Emits nothing at all.** No updates, no error, state untouched |
| 4 | `interrupt()` on a fresh thread | Pauses normally; `state.next == ("gate",)` |
| 5 | Plain state input sent while paused | New message **is appended** to `messages`, but the graph **stays paused** and re-emits the same `__interrupt__`. The new turn is never processed |
| 6 | `Command(resume=...)` on a thread id never seen before | **No error.** Runs from START with empty input and hits the interrupt with zero user messages |

Consequences for this design:
- **#3 is a live bug source under Q8A.** A stale or double-clicked resume yields an empty SSE stream, and
  `api.py`'s `_generate` maps empty output to `502 "The model returned an empty answer."` — a model error
  reported for a routing problem. The resume path must detect "no pending interrupt" explicitly.
- **#5 is the abandoned-pause case** and it silently eats the user's message. Q11 addresses it.
- **#6** means a bogus resume on an unknown thread starts a fresh run with no user message, which under
  Q5 lands in the refusal path. Weird but not harmful; still worth an explicit guard.

Verified via Context7 (`/websites/developers_openai_api`, 2026-09-04):

- **`gpt-5-mini`** — 400,000-token context window, **128,000 max output tokens**, supports reasoning
  tokens, knowledge cutoff 2024-05-31, text+image in / text out.
- **`max_output_tokens` includes reasoning tokens** — "an upper bound for the number of tokens that can
  be generated for a response, **including visible output tokens and reasoning tokens**."

Verified empirically against the live OpenAI API through this repo's own `llm._build_client` (2026-09-04):

- `gpt-5-mini` at the repo's hardcoded `temperature=0.0` **works** — streams plain text normally.
  (The concern that GPT-5 reasoning models reject non-default temperature does **not** apply here.)
- `gpt-5-mini` at `temperature=1.0` works.
- `gpt-5-mini` with `with_structured_output(..., method="json_schema", strict=True)` works.
- **No change to `llm.py` or `config.LLMSettings` is required.** `_build_client` already passes
  `max_completion_tokens` (the GPT-5-compatible parameter), not `max_tokens`. Adopting `gpt-5-mini` is a
  new `LLMSettings(...)` in the report agent's own `config.py`, exactly per repo convention.

## Settled decisions

- **Q1 — What the human approves** — an **outline, before the report is written**, not a finished draft.
  _(rationale: cheap checkpoint; puts the pause before the expensive call, so the documented
  re-run-on-resume behaviour costs almost nothing)_
  - Challenged on: the outline gate is blind to the failures that actually matter (wrong claims, thin
    sourcing, bad prose), and it grants exactly one exit — after approval you get whatever comes out.
    → Held (settled by non-revision).
  - Consequences: the interrupt sits between outline generation and report generation. Forecloses a
    "revise the finished report" flow.

- **Q2 — How a turn enters the report branch** — the **classifier gets a third destination**;
  plain-language requests like "write me a report on X" route there. No button, no slash command.
  _(rationale: in the grain of the existing `Destination` Literal; the approval gate makes a misroute
  cheap to recover from)_
  - Challenged on: no routing-accuracy measurement exists, a third class degrades the existing two-way
    split, and a misroute now *stops the conversation* to demand approval instead of merely giving a
    slightly worse answer. → Held (settled by non-revision).
  - Consequences: `Destination` becomes a three-way `Literal`; `CLASSIFY_SYSTEM_PROMPT` gains a third
    rule. Combined with Q5, a misroute in a fresh chat produces a refusal rather than an answer —
    the accepted worst case.

- **Q3 — Where the report's material comes from** — the **existing conversation only**. The report
  branch performs no search or fetch of its own. _(rationale: keeps the branch cheap and the rule
  simple; the material is already cited)_
  - Challenged on: a report built from an answer the user already read risks collapsing into "the same
    words with headings," which a plain **Download .md** button delivers with no agent at all.
    → Held; resolved by Q6, which makes the report a *synthesis across turns* rather than a reformat
    of one answer. That synthesis is the thing a download button cannot do.
  - Consequences: no Brave/trafilatura call in this branch. The 422 `NoSourcesError` path cannot fire
    here. Makes Q4's revision loop cheap, since no round re-runs research.

- **Q4 — What the gate accepts** — **approve, cancel, or free-text revision**. Revision redraws the
  outline and pauses again. _(rationale: the revision loop is the part of the pattern worth building
  once; a binary veto barely exercises it)_
  - Challenged on: free-text revision over a fixed corpus writes cheques the corpus cannot cash — "add
    a section on Poland" when the thread never mentioned Poland. → Held; the underlying question was
    deferred to the frontier (Q10) rather than settled here.
  - Consequences: the branch loops back on itself; the interrupt can fire many times in one turn.
    Revision rounds are unbounded unless capped — see Q10/flags.

- **Q5 — A report request with nothing to build from** — **refuse and explain**. The branch tells the
  user to ask about the topic first, then request the write-up. It does not research, and it does not
  write from model memory. _(rationale: keeps the rule absolutely simple — reports are made of
  researched answers, full stop)_
  - Challenged on: this refusal will be the *most common first experience* of the feature, since anyone
    discovering it will try it cold; and combined with Q2 it converts a classifier misroute in a fresh
    chat into a confusing refusal where an ordinary answer would have served. → Held.
  - Consequences: rejects the "run the expert first, then offer the report" flow, which would have
    reversed Q3. The refusal copy is user-facing product surface and must teach the two-step.

- **Q6 — How much conversation the report reads** — the **whole recent window**, the same 20-message
  slice `classify` and `chat` already use. The report is a synthesis across turns, not a reformat of
  the last answer. _(rationale: synthesis is the only thing here a download button cannot already do)_
  - Challenged on: 20 messages of expert answers can exceed `gpt-4o-mini`'s 128k input context, so this
    commits to a truncation or summarization strategy — deciding which parts of a user's conversation
    get silently dropped — as a side effect of a feature framed as a learning exercise. → Held.
  - Consequences: opens Q7 (overflow strategy) as a required, non-optional piece of work.
    Also makes the outline gate the place where report *scope* is negotiated, since the branch reads
    everything and the user narrows it at the pause.

- **Q8 — Pause/resume transport** — **the existing endpoint accepts both**.
  `POST /api/run_pipeline/stream` takes either `{query, thread_id}` or `{resume, thread_id}`.
  A new SSE frame type carries the pause to the browser. _(rationale: one door, one frontend code path)_
  - Challenged on: the request body becomes a union whose "exactly one of" rule is easy to get wrong;
    and probe finding #3 means a `resume` arriving for an un-paused thread currently produces a
    misleading `502`. → Held. Noted in A's favour: a single endpoint is the only place that can *see*
    the collision in Q11 (a `query` arriving while the thread is paused) and act on it.
  - Consequences: `RunPipelineRequest` becomes a union; `test_api.py` and all three guidance files
    change. The resume path **must** explicitly detect "no pending interrupt" rather than relying on
    the empty-output branch.

- **Q9 — Markdown delivery** — **client-side**. The report text has already streamed into the browser;
  a **Download .md** (`Blob`) and a **Copy** button act on it. No new endpoint.
  _(rationale: zero backend work, and the server alternative's main advantage does not exist — the
  frontend never rehydrates history, so neither option survives a reload)_
  - Challenged on: the browser only ever receives text capped at `MAX_ANSWER_CHARS = 50_000`, while the
    checkpoint holds the full message — so a very long report downloads as silently truncated Markdown
    with a `.md` extension that looks complete. (This correction was issued after the round; the user
    held with it stated.) → Held.
  - Consequences: no `GET /api/report/...` endpoint, and no new `thread_id`-keyed read surface.
    A report longer than 50,000 characters is silently clipped on download — accepted risk.

- **Q10 — Revision requesting absent material** — **the gate refuses on the spot** and re-shows the
  unchanged outline, telling the user to research the topic first.
  _(rationale: the gate is the negotiation point chosen in Q1; failing there is failing at the cheapest
  moment)_
  - Challenged on: this asks the outline model to judge what the conversation "covers," and it will err
    in both directions; a confident wrong refusal is more annoying than an honest gap section.
    → Held. Noted in A's favour: Q11A gives a clean escape — ask about the topic (which cancels the
    report), then request the report again.
  - Consequences: the outline node's prompt must ground every proposed section in thread material and
    be able to decline an addition.

- **Q11 — A new question arrives while paused** — **the new question wins**. The server cancels the
  pending pause and answers the new turn normally. The report request is dropped.
  _(rationale: a chat window that refuses to accept a message is a bad chat window, and the outline is
  cheap to regenerate)_
  - Challenged on: an explicitly-made request vanishes with no confirmation — the exact failure the
    approval gate exists to prevent. → Held.
  - Consequences: overrides probe behaviour #5, which would otherwise swallow the message and re-emit
    the same interrupt. Requires the server to clear the pending interrupt before running the new turn.
    Directly creates Q14: the same text box now produces both revisions and new questions.

- **Q14 — Telling a revision from a new question** — **a second classifier decides**. While the thread
  is paused, one small structured call sorts the typed text into revise / new question / cancel, and the
  server acts accordingly. _(rationale: the only option that keeps both Q4B and Q11A intact)_
  - Challenged on: it adds a second unmeasured classifier to an app with no routing-accuracy measurement
    anywhere, and its misroutes are expensive — reading "drop the third section" as a new question
    cancels the report and answers a question nobody asked. The alternative (Approve/Cancel buttons,
    typing always means revise) is deterministic and free but would have reversed Q11A. → Held.
  - Consequences: a three-way intent classifier, its own prompt and `LLMSettings`. The frontend's paused
    state needs no buttons — a single text box is sufficient, though buttons may still be added as
    shortcuts.

- **Q7 — Context-overflow strategy** — **silent newest-first truncation to a character budget**, plus a
  **model change: the report writer uses `gpt-5-mini`** (400k context) rather than `gpt-4o-mini`.
  _(rationale: with a 400k window the overflow case effectively stops existing, so it does not warrant
  user-facing surface)_
  - Challenged on: the truncation path now essentially never fires, which makes it untested code that
    will misbehave the one time it does; and more importantly the 400k window removes the cost/overflow
    reasoning that motivated Q6's 20-message limit in the first place. → Pending (Q15).
  - Consequences: `REPORT_LLM_SETTINGS(model="gpt-5-mini", ...)` in the report agent's `config.py`.
    No shared-module change. Two sizing decisions follow — see flags.

- **Q15 — How much of the thread the report reads** — **the whole thread**, every message since the
  chat began, not the 20-message window. _(rationale: `gpt-5-mini`'s 400k context removes the constraint
  that motivated the window, and `state["messages"]` already holds the full history — omitting the slice
  is less code, not more)_
  - Challenged on: thread length is uncapped anywhere in this app, and the report is the one operation
    whose cost scales with it; and the silent truncation chosen in Q7A becomes something long-thread
    users actually hit and are never told about. → Held.
  - Consequences: **supersedes Q6's 20-message window for the reporter only** — `classify` and `chat`
    keep `HISTORY_WINDOW_MESSAGES`. Reactivates Q7A's truncation guard as the real safety net rather
    than near-dead code, which answers the objection raised against Q7A in Round 6.

- **Q12 — Module layout** — **its own package, `app/src/agents/reporter/`**, compiled as a subgraph and
  invoked inside an orchestrator node, exactly as `expert` is. The agent is named **`reporter`**.
  _(rationale: matches the convention `CLAUDE.md` states flatly, and the expert precedent)_
  - Challenged on: an argument that a nested graph regenerates the outline on every resume, making the
    package layout permanently more expensive on the revision loop. **That challenge was withdrawn** —
    it was an untested inference and measurement disproved it (see below). No cost objection to A
    survives.
  - Consequences: `agents/reporter/{__init__,graph,state,config,prompts}.py` and `nodes/`. Must be
    invoked inside a node, never via `add_node` — the reporter's state shares no key with the
    orchestrator's, and LangGraph 1.0.1 would silently discard its result.

## Design tree

- **Product shape**
  - Q1 What the human approves → SETTLED (outline, pre-write)
  - Q2 How a turn enters the branch → SETTLED (classifier third destination)
  - Q4 What the gate accepts → SETTLED (approve / cancel / free-text revision)
- **Report material**
  - Q3 Research vs. reshape → SETTLED (reshape only)
    - Q5 Nothing to reshape → SETTLED (refuse and explain)
    - Q6 How much of the thread → SETTLED (whole 20-message window)
      - Q7 Context-overflow strategy → OPEN
    - Q10 Revision asking for absent material → OPEN
    - Q7 Context-overflow strategy → SETTLED (silent truncation + `gpt-5-mini`)
      - Q15 Does the 400k window reopen Q6's 20-message limit? → SETTLED (read the whole thread;
        supersedes Q6's window for the reporter)
    - Q10 Revision asking for absent material → SETTLED (gate refuses on the spot)
- **Delivery layer**
  - Q8 Pause/resume transport and API contract → SETTLED (one endpoint, union body)
  - Q9 How the Markdown reaches the user → SETTLED (client-side Blob + Copy)
  - Q11 New question arrives while paused → SETTLED (new question wins, pause cancelled)
    - Q14 Revision vs. new question disambiguation → SETTLED (second three-way classifier)
- **Implementation shape**
  - Q12 Module layout → SETTLED (own `agents/reporter/` package, expert-style subgraph)
    - Q16 Subgraph vs. node-library flavour of the package → PRUNED (measured identical cost;
      convention decides)
  - Q13 Test strategy without a live model or database → PRUNED (see below)

## Current frontier (open questions)

_Empty. Every live branch was visited._

**Pruned:**
- **Q13 — Test strategy.** Every answer leads to the same work: unit tests mirroring `src/` under
  `tests/unit_tests/agents/reporter/`, fakes at the `llm.py` boundary (the existing pattern in
  `test_chat.py` / `test_answer.py`), an `InMemorySaver`-backed interrupt/resume test in
  `tests/integration_tests/`, and source-text assertions in `test_frontend_ux.py` for the new SSE frame
  and the download button. Recorded as design, not as an open question.
- **Model choice for the outline node and the paused-state classifier.** Repo convention already
  settles it: hardcoded per-node `LLMSettings` in `agents/reporter/config.py`, chosen at implementation
  time. Not a design decision.
- **Q16 — subgraph vs. node-library flavour of the `reporter` package.** Measured identical
  (3 outline calls for 2 revisions + 1 approval, both layouts), so convention decides: expert-style
  compiled subgraph.

## Carried as flags, not decisions

- **Guidance-file rule** — the `{query, thread_id}` request shape is documented as exact in
  `CLAUDE.md`, `AGENTS.md`, and `.github/copilot-instructions.md`. Any resume mechanism changes at
  least one of those, and the repo rule requires all three updated in the same change, plus
  `ai_tools_tables.md` if tooling changes.
- **Refusal copy is product surface** (from Q5) — the "ask me first" message must teach the two-step
  workflow, and it is what most users will see first.
- **Classifier misroute cost rose** (from Q2 + Q5) — a fresh-chat misroute now yields a refusal
  instead of an answer. Accepted, but worth a routing check in `tests/manual_quality/cases.json`.
- **`ANSWER_NODES` filter** — `api.py` forwards AI messages only from nodes named `answer` and `chat`.
  The report branch's writing node must be added there or its tokens will never reach the browser.
- **Stale-resume guard (probe #3)** — `Command(resume=...)` on an un-paused thread emits nothing, which
  `_generate` currently reports as `502 "The model returned an empty answer."` The resume path must
  check for a pending interrupt (`aget_state(config).next`) and return a distinct, honest error.
- **Unknown-thread resume guard (probe #6)** — a resume for a thread id never seen starts a fresh run
  with no user message. Guard with the same pending-interrupt check.
- **Reasoning-token budget** — `max_output_tokens` on `gpt-5-mini` covers reasoning *and* visible output.
  `REPORT_LLM_SETTINGS.max_output_tokens` must be sized for both or reports come out short.
  gpt-5-mini's ceiling is 128,000.
- **Reasoning-model latency** — `LLMSettings.timeout_seconds` defaults to 60.0; a long synthesis report
  on a reasoning model may exceed it. Needs a deliberate value. nginx allows 600s and the frontend
  aborts at 600s, so there is headroom.
- **Truncation budget** (Q7 + Q15) — reading the whole thread makes the newest-first character budget
  the real safety net. It needs a concrete number and a direct unit test. Truncation is silent by
  decision (Q7A); long-thread users will not be told their report omitted early exchanges.
- **Unbounded thread cost** (Q15) — nothing in this app caps thread length, and the report is the one
  operation whose cost scales with it. Accepted risk; no cap decided.
- **Revision-round cap** (Q4) — no cap decided. Each round costs exactly one outline call (measured),
  so per-round exposure is bounded but total exposure is not. Needs a cap or an explicit accepted risk.
- **50,000-char download clip** (from Q9) — accepted; the downloaded `.md` gives no indication it was
  truncated.


## Approaches considered

Three overall shapes were on the table. The design tree settled individual decisions; this records that
the overall shape was chosen, not inherited.

1. **Report as a formatting step on the last answer** — a "Download .md" button plus light restructuring,
   no agent, no pause. *Rejected:* Q6/Q15 chose synthesis across the whole conversation, which a
   formatting step cannot do. This shape is what the design would collapse into if the reporter only
   ever read one answer.
2. **Report as a researching agent** — its own Brave/trafilatura cycle, like the expert. *Rejected at
   Q3:* doubles the most expensive path, duplicates research the thread may already contain, and puts a
   hard-failing 422 path behind an approval gate — the user commits, then it dies.
3. **Report as a synthesis agent over the existing thread, gated by an outline approval** — *chosen.*
   It is the only shape where the human-in-the-loop pause does real work: the gate is where report scope
   is negotiated, which matters precisely because the reporter reads everything and the user narrows it.

## Testing

Recorded as design (Q13 pruned — every answer led to the same work):

- `tests/unit_tests/agents/reporter/test_{outline,gate,write}.py`, mirroring `src/`, with fakes at the
  `llm.py` boundary — the existing pattern in `test_chat.py` and `test_answer.py`.
- An `InMemorySaver`-backed interrupt/resume test in `tests/integration_tests/`, covering: pause emitted,
  revision redraws and re-pauses, approval writes, cancel ends cleanly.
- Direct unit tests for the three guards the probes exposed: resume on an un-paused thread, resume on an
  unknown thread id, and the newest-first truncation budget.
- `test_api.py` for the union request body ("exactly one of `query` / `resume`") and the new SSE frame.
- Source-text assertions in `test_frontend_ux.py` for the pause UI and the download/copy controls,
  matching how the frontend is already tested.

## Guidance files to update

Repo rule: every change updates `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` together.
This change touches, in all three: the orchestrator graph diagram, the exact API request shape, the SSE
frame list, the agent inventory, and the frontend description. No plugin/skill/tool changes, so
`ai_tools_tables.md` is untouched.

## Round log

### Round 1 — Q1 (what the human approves) + Q2 (how a turn enters the branch)
Q1 offered outline-before-writing (A), draft-after-writing (B), or both gates (C), with the
re-run-on-resume constraint argued in favour of A. Q2 offered a classifier third destination (A)
vs. an explicit button on an existing answer (B).
Lean was A and A (both weak). **User answered:** Q1 A, Q2 A.
**Pushed back on** Q1: the outline gate is blind to the failures that actually matter, and grants one
exit only. **Pushed back on** Q2: no routing-accuracy measurement exists, a third class degrades the
existing split, and a misroute now stops the conversation rather than merely degrading an answer.
→ Both held (settled by non-revision; user proceeded to the next round without revising).

### Round 2 — Q3 (research vs. reshape) + Q4 (what the gate accepts)
Q3 offered "the report researches" (A) vs. "the report reshapes the conversation" (B), using a
fresh-chat request as the discriminating case. Q4 offered binary approve/cancel (A) vs. free-text
revision (B).
Lean was A (medium) and B (weak). **User answered:** Q3 B, Q4 B.
Noted that B+B is coherent: Q3B removes the research, so the Q4 revision loop is cheap — the trap
named in Q4's counter-case does not fire.
**Pushed back on** Q3B: a report built from an answer already read collapses toward "the same words
with headings," which a plain Download-.md button delivers with no agent. **Pushed back on** Q4B:
free-text revision over a fixed corpus writes cheques the corpus cannot cash.
→ Both held. Q3B's objection was answered by Q6B (synthesis across turns); Q4B's objection was
deferred to the frontier as Q10.

### Round 3 — Q5 (nothing to build from) + Q6 (how much conversation)
Q5 offered refuse-and-explain (A), research-first-then-offer (B), or write-from-memory (C), noting
that B would quietly reverse Q3 and offering to re-open Q3 instead. Q6 offered last-answer-only (A)
vs. the whole 20-message window (B), with the 128k context-overflow risk stated.
Lean was B (weak) and B (strong). **User answered:** Q5 A, Q6 B.
**Pushed back on** Q5A: the refusal will be the most common first experience of the feature, and
combined with Q2 it turns a fresh-chat misroute into a confusing refusal. **Pushed back on** Q6B:
it commits to a truncation strategy that silently drops parts of a user's conversation.
→ Both held. Q6B retroactively answers Q3B's objection: synthesis across turns is what a download
button cannot do. Q7 (overflow strategy) added to the frontier as required work.

### Round 4 — Q8 (pause/resume transport) + Q9 (Markdown delivery)
Q8 offered one endpoint with a union body (A) vs. a separate `/resume` endpoint (B). Q9 offered a
client-side `Blob` download (A) vs. a server `GET /api/report/{id}` (B), with the finding that the
frontend never rehydrates history — nullifying B's durability advantage.
Lean was B (weak) and A (strong). **User answered:** Q8 A, Q9 A.
**Conceded** in Q8A's favour: only a single endpoint can see the query-arrives-while-paused collision.
**Pushed back on** Q8A: a union body lets `resume` arrive for an un-paused thread; probe #3 shows that
produces a misleading 502. **Issued a correction on** Q9: the browser receives only text capped at
`MAX_ANSWER_CHARS = 50_000` while the checkpoint holds the full message, so a long report downloads
silently truncated — a real A-vs-B difference missed when the lean was called "strong."
→ Both held.

### Round 5 — Q11 (new question while paused) + Q10 (revision for absent material)
Preceded by a six-case probe of langgraph 1.0.1 interrupt behaviour (recorded above), which supplied
the verified default for Q11: the user's new question is appended to history, never answered, and the
same interrupt is re-emitted.
Q11 offered new-question-wins (A) vs. pause-wins-and-says-so (B). Q10 offered gate-refuses (A),
report-notes-the-gap (B), or no special handling (C).
Lean was A (weak) and A (medium). **User answered:** Q11 A, Q10 A.
**Pushed back on** Q10A: the outline model will misjudge coverage in both directions.
**Surfaced a collision** rather than a plain objection on Q11A: it contradicts Q4B, because one text box
must now produce both revisions and new questions with nothing deciding which. Escalated to Q14.
→ Both held; Q14 added.

### Round 6 — Q14 (revision vs. new question) + Q7 (context overflow)
Q14 offered buttons-decide/typing-always-revises (A, which would reverse Q11A) vs. a second classifier
(B). Q7 offered silent truncation (A), truncation announced at the gate (B), or summarization (C, with
its citation loss called disqualifying).
Lean was B (weak) and B (medium). **User answered:** Q14 B, Q7 A — **and changed the report writer's
model to `gpt-5-mini`** for its 400k context window.
Verified the model claim (400k context / 128k output, confirmed) and tested `gpt-5-mini` through the
repo's own `llm._build_client`: it works at the hardcoded `temperature=0.0`, streams, and supports
strict structured output. The anticipated GPT-5 temperature incompatibility does not apply; no
shared-module change is needed.
**Pushed back on** Q14B: a second unmeasured classifier whose misroutes destroy work; it is in fact a
three-way call (revise / new question / cancel). **Pushed back on** Q7A: at 400k the truncation path
becomes near-dead code, and — more consequentially — the 400k window removes the cost/overflow
reasoning that motivated Q6's 20-message limit. Escalated to Q15.

### Round 7 — Q15 (window size after the model change) + Q12 (module layout)
Preceded by two probes: a nested subgraph with **no checkpointer of its own** can interrupt and resume
correctly (the parent's checkpointer carries it), and its interrupt is emitted **twice** — once under
`ns=('reporter:<uuid>',)` and once under `ns=()` — so `api.py`'s existing namespace filter passes exactly
one frame with no API change. A second probe showed that splitting generate/pause into two top-level
nodes runs the expensive node once per approval.
Q15 offered keeping the 20-message window (A) vs. reading the whole thread (B). Q12 offered an
`agents/report/` package (A) vs. plain orchestrator nodes (B).
Lean was B (weak) and B (medium). **User answered:** Q15 B, Q12 A, and **named the agent `reporter`**.
**Pushed back on** Q15B: thread length is uncapped and silent truncation now becomes user-visible in
practice. Noted in its favour that Q15B reactivates Q7A's truncation guard, answering the Round 6
objection that it was dead code.
**On Q12:** flagged that "own package" had two flavours differing by a measured amount and declined to
guess. Measured both.

**Correction issued.** The Round 7 claim that a nested subgraph "restarts the child from START and
regenerates the outline every round" was an untested inference and is **false**. Measured over a
realistic loop (initial request + 2 revisions + 1 approval), both layouts cost **3 outline calls** —
identical and optimal. LangGraph persists subgraph progress in the parent's checkpoint namespace, which
is the same mechanism that made the nested interrupt resume correctly. The sole objection to Q12A
therefore does not exist, and the A1/A2 ambiguity dissolved: with cost equal, convention decides.
→ Q15 B and Q12 A (expert-style compiled subgraph) settled. Frontier empty.
