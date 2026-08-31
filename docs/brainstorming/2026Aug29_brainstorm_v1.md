# Next development step for GeopoliticAI — orchestrator/conversational agent vs. other paths

**Started:** 2026-08-29
**Status:** Complete (frontier empty)
**Mode:** single (one question per round, default)

## Target design

A two-agent system with a persistent conversation, shipped as one release. Development phase —
real users are a long-term goal, not this release's constraint.

### Shape

```
orchestrator graph:
    START -> classify -> [ expert graph ]  -> END      (geopolitical)
                      -> chat              -> END      (everything else)
```

- **Orchestrator** owns the conversation and is the entry point. It is a **general assistant**:
  non-geopolitical turns it answers itself, from its own knowledge, with no sources (Q9).
  It lives at `app/src/agents/orchestrator/` with its own `prompts.py` and `config.py`.
- **`classify`** is one structured-output call, not a tool-calling agent (Q2). It returns both
  the route and a self-contained rewrite of the turn:
  `{destination: Literal["geopolitical", "other"], standalone_query: str}`. A plain
  `add_conditional_edges` fork follows. The prompt carries **no** bias toward either branch (Q5b).
- **Expert** is unchanged — still `START -> search_and_fetch -> answer -> END`, still
  `{query, sources, answer}`, still one plain string in. It is **nested as a compiled subgraph
  node** (Q11), so it still runs standalone in LangGraph Studio.
- **Threads persist in Postgres** (Q1b). The frontend mints a sticky `thread_id`, keeps it in
  browser storage, sends it on every request, and offers a **New chat** button (Q13). Only the
  **last 10 turns** are passed to the model (Q14).

### What changes, file by file

- `app/src/agents/orchestrator/` — new: `graph.py`, `nodes/`, `prompts.py`, `config.py`, `state.py`.
- `app/src/agents/expert/` — untouched.
- `api.py` — request body becomes `{query, thread_id}`; `_astream_answer` is rewritten to pass
  `subgraphs=True` and handle namespace-prefixed `(namespace, data)` events for both branches;
  progress inference becomes route-aware with **three** constants — `THINKING_PROGRESS`
  emitted immediately, `SEARCH_PROGRESS` only on the expert branch, `ANSWER_PROGRESS` on the
  first token (Q4); `DATABASE_URL` becomes mandatory (Q12b); the checkpointer is built here and
  passed into `build_graph(checkpointer=...)` (Q12c); `import database` and the `log_run` call
  are removed (Q12a).
- `database.py`, `tests/unit_tests/test_database.py` — **deleted**. `prompt_logs` goes with them;
  Phoenix is the observability story (Q12a).
- `pyproject.toml` — drop `asyncpg`, add `langgraph-checkpoint-postgres` (psycopg 3). One driver.
- `frontend/index.html` — sticky `thread_id`, New chat button, third progress state.
- `langgraph.json` — gains the orchestrator graph alongside `expert`.
- `README.md`, `CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md` — the "never answers
  from background knowledge" claim and every `prompt_logs` reference must be rewritten.
- `tests/unit_tests/test_api.py` — nine `api.database.log_run` patch sites and three assertions
  removed; `:226` repointed at the orchestrator graph so a broken subgraph stream fails CI.

## Context verified

- Repo root `/home/rafal/repos/geopoliticai`. Brainstorms today: none → this session claims `v1`.
- **The chat UI is not conversational at all.** `frontend/index.html:445` posts only
  `{query: text}` to `/api/run_pipeline/stream`. The `messages` array is client-side
  display state; **no prior turn ever reaches the backend**. Follow-ups like "and Poland?"
  are answered as if asked cold.
- **No persistence of conversation.** `PipelineState` (`app/src/agents/expert/state.py`)
  is exactly `{query, sources, answer}`, no `messages`, no reducers. No checkpointer is
  compiled (`graph.py:build_graph` → `pipeline.compile(name="expert")`). `build_runtime_config`
  accepts a `thread_id` but `api.py` **never passes one** — it calls `build_runtime_config()` bare.
- **Every request costs 3 Brave batches + fetches + one LLM call**, unconditionally.
  "hi" costs the same as a real research question. `search_and_fetch` always runs
  (`START -> search_and_fetch -> answer -> END`).
- **Answer model is `gpt-4o-mini`** (`agents/expert/config.py:ANSWER_LLM_SETTINGS`),
  temperature 0.0, 16k max output, 60s timeout. Shared default in `config.py` is the same.
- **Source policy**: 28 allow-listed domains, 3 fixed batches, `max_per_domain=2`,
  `fetch_candidates=10 / keep_sources=8`, 6 hard-paywalled domains deferred.
  All English-language, US/UK-centric. No query rewriting — the user's raw query goes to Brave.
- **Prompt** (`prompts.py:ANSWER_SYSTEM_PROMPT`) forbids parametric knowledge entirely
  ("Treat your own background knowledge as unavailable") and mandates inline citations.
- **No evals of any kind.** `app/tests` = `unit_tests` + one `integration_tests/test_expert_graph.py`.
- **No accounts, no sessions** (see the shared Basic credential below — that is the whole
  identity story). Rate limit is in-process, per-IP, 20 req / 60 s.
- **DB**: `prompt_logs(datetime, prompt, ip, output)`. `log_run` writes once per *successful*
  run, silently swallows failures. Failed runs recorded nowhere.
- **Deps (installed, from `app/uv.lock`)**: `langgraph 1.0.1`, `langgraph-prebuilt 1.0.1`,
  `langgraph-checkpoint 3.0.1`, `langchain-core 0.3.83`, `langchain-openai`. The `langchain`
  package itself is **not** a dependency. No `langgraph-checkpoint-postgres`.
  Phoenix tracing is wired (API lifespan + graph module scope).
- **A tool-calling orchestrator needs no new dependency.** Corrects an earlier note in this
  file: `langchain.agents.create_agent` would indeed be a new dep, but
  `langgraph.prebuilt.create_react_agent` is **already installed** and exported
  (`langgraph/prebuilt/__init__.py:3`), as are `ToolNode` and `ValidationNode`.
  `langgraph.checkpoint.memory` (InMemorySaver) is present too — so Q1b's decision costs
  zero new packages.
- Compose runs backend + frontend + postgres + phoenix; `.env` is single, at repo root.
- **There is a real deployment.** `docker-compose.prod.yml` publishes the frontend on
  80/443, mounts `/etc/letsencrypt` read-only, and `frontend/docker-entrypoint.sh` writes
  an htpasswd file from `AUTH_USER`/`AUTH_PASSWORD` — so production is **one shared HTTP
  Basic credential** in front of nginx. Not "no auth": a single door key, no per-user identity.
- **`prompt_logs` is the only usage evidence that exists** and it is already collecting real
  queries (prompt, ip, output, datetime) from that deployment. Nobody has read it. It is the
  fact that would settle whether small-talk/off-topic traffic is a real problem or a guess.
- **The repo speaks `asyncpg`, the checkpointer speaks `psycopg`.** `app/pyproject.toml:19`
  pins `asyncpg>=0.29,<1.0` and `database.py` builds an asyncpg pool. Context7 on
  `langgraph-checkpoint-postgres`: *"The library defaults to installing Psycopg 3."*
  `AsyncPostgresSaver.from_conn_string(...)` + a mandatory `.setup()` to create its tables.
  So a Postgres checkpointer means **two drivers and two pools against the same database**.
- **The backend is single-process.** `app/Dockerfile:20` is
  `uvicorn api:app --host 0.0.0.0 --port 8000` with no `--workers`, and compose adds none.
  So an in-memory checkpointer is *correct* here — no cross-worker thread loss. The
  in-process per-IP rate limiter already depends on this same property. Prod's
  `restart: unless-stopped` means threads are lost on redeploy, which is the known tradeoff.
- **The expert hard-errors on a query it cannot search.**
  `agents/expert/nodes/search_and_fetch.py:23` raises `NoSourcesError` ("No approved sources
  were found for this query. Try rephrasing it.") when Brave returns zero allow-listed
  candidates, and again at line 30 when none can be fetched/extracted. `NoSourcesError.status`
  is 422 (`models.py:26-29`) and the API reports it in an SSE `error` frame. So a bare
  follow-up fragment sent to the expert either errors out or silently searches the wrong thing.
- **Removing `prompt_logs` is cleanly bounded.** All call sites: `api.py:21` (`import
  database`), `:61`/`:63` (lifespan init/close), `:242` (`log_run`); `app/src/database.py`;
  `tests/unit_tests/test_database.py` (whole file); nine `api.database.log_run` patch sites in
  `test_api.py`, two of which assert logging behaviour directly (`:84`, `:110`, `:147`);
  `pyproject.toml:19` (`asyncpg`). Compose's `DATABASE_URL` stays — the checkpointer needs it.
- **`_resolve_client_id` survives the removal.** It looks like it exists only to fill
  `prompt_logs.ip`, but `_enforce_rate_limit` calls it too (`api.py:126`), so the
  rightmost-`X-Forwarded-For` logic stays load-bearing for rate limiting.
- **Phoenix already covers what `prompt_logs` covered, and more.** Tracing is wired in the API
  lifespan and at `graph.py` module scope, exporting full prompt/response content with no
  redaction by design, including failed runs — which `log_run` never recorded, since it writes
  only after success. The one thing lost is the IP-to-query association.
- **The "Searching..." frame is emitted unconditionally, before anything runs.**
  `api.py:221` yields `{"type": "progress", **SEARCH_PROGRESS}` with the label
  *"Searching and reading sources..."* as the very first frame, then
  `ANSWER_PROGRESS` ("Writing the answer...") on the first token (`:224`). Both labels are
  hardcoded in `api.py:43-47` and inferred by the API, not read from graph events. On a chat
  turn that searches nothing, the first frame would be a lie.
- **The database is optional today.** `api.py:59-61` — `db_url = os.getenv("DATABASE_URL")`,
  then `if db_url: await database.init_pool(db_url)`. With no `DATABASE_URL` the app runs
  fine and simply logs nothing. A Postgres checkpointer inverts that: without a database there
  is no conversation state at all.
- **`graph.py` compiles at module scope** (`graph = build_graph()`), and that module is what
  `langgraph dev` imports. A checkpointer needing a live connection at import time therefore
  makes Postgres a hard requirement for Studio too.
- **One test actually exercises the streaming loop.**
  `tests/unit_tests/test_api.py:226` `test_astream_answer_yields_only_answer_node_text` —
  its own docstring calls it *"the one test that actually executes `_astream_answer`"*. It
  builds a real graph with `FakeListChatModel`, monkeypatches the search boundary, and asserts
  the yielded chunks. Every other API test patches `api._astream_answer` away. So a
  subgraph-streaming regression **is** catchable by the existing suite, provided this test is
  repointed at the orchestrator graph.
- **Nested subgraph tokens are dropped by default.** Verified in the installed
  `langgraph 1.0.1`: `langgraph/pregel/_messages.py:137` —
  `if not self.subgraphs and len(ns) > 0 and ns != self.parent_ns: return`.
  `astream(stream_mode="messages")` defaults to `subgraphs=False`, so an expert compiled as a
  nested subgraph emits **no** answer tokens. Passing `subgraphs=True` fixes that but changes
  the emitted shape to `(namespace, data)` (`langgraph/pregel/main.py:2763-2767`), which breaks
  `_astream_answer`'s two-tuple unpacking — the exact trap its existing comment warns about.
- **`TAG_NOSTREAM = "nostream"`** (`langgraph/constants.py:24`). Tagging an LLM call with it
  makes `on_chat_model_start` skip registration, so its tokens never enter the messages stream.
  This is the clean way to keep a classifier call out of the user-visible stream.
- **`create_react_agent`'s internal nodes are named `agent` and `tools`**
  (`langgraph/prebuilt/chat_agent_executor.py:770-846`), not `answer` — so a tool-calling
  orchestrator would require rewriting the `api.py:200` filter regardless.
- **Streaming filter is a chokepoint.** `api.py:200` drops every token whose
  `metadata["langgraph_node"] != "answer"`. Any node that emits user-visible text must be
  named `answer` or that filter must change — true for every option considered.
- **The repo's own history is a record of deliberate narrowing**: `#4` added Polish infosphere
  source sets, `#5` added a "people" (Reddit/X/Threads) perspective agent — both are gone,
  removed across the Aug24→Aug28 cleanup/simplification arc (`#22`, `#24`, `#25`). The current
  two-node graph is the *result* of three consecutive simplification plans, not a starting point.

## Settled decisions

- **Q1 — Development phase; the next release is the orchestrator** — real users are a
  long-term goal but not this release's constraint. Ship one orchestrator agent in front of
  one deliberately simple expert agent: geopolitical/political turns are delegated to
  `expert`, everything else the orchestrator answers itself.
  _(rationale: user's call — the expert is to stay simple, and the orchestrator is the
  capability being added.)_
  - Challenged on: PENDING — the orchestrator answering "other" questions itself is the
    first uncited, parametric-knowledge answer this product has ever produced, and a
    misroute is silent; plus the router classifies single turns with no history, so
    follow-ups are structurally unclassifiable.
  - Consequences: prunes Q1's options A/C/D as *this* release's focus. Keeps Q6 (source
    policy) and Q7 (model/cost) alive as later work. Raises the stakes on Q5 (routing
    correctness) and couples Q3 (memory) into the same release.

- **Q1b (REVISED in round 9) — Threads with a Postgres checkpointer** — the release ships
  orchestrator + thread identity + `langgraph-checkpoint-postgres`. Originally settled in
  round 3 as "InMemorySaver now, Postgres later"; reversed once the Q13 restart-amnesia
  problem made durability a correctness issue rather than a convenience.
  _(rationale: with a sticky browser-held `thread_id`, an in-memory saver means every deploy
  leaves the screen showing a conversation the model cannot remember. Persisting threads
  removes that failure instead of papering over it.)_
  - Challenged on (round 2): a checkpointer buys durability rather than follow-up resolution;
    psycopg-vs-asyncpg driver duplication; `thread_id` as an unauthenticated bearer token
    behind one shared Basic credential. → Held on the third round of asking, with a better
    reason than the first time.
  - Consequences: `langgraph-checkpoint-postgres` becomes a real dependency (psycopg 3, on top
    of the existing `asyncpg`), `.setup()` must run to create its tables, and **the database
    stops being optional** — `api.py:59-61` currently treats it as a nice-to-have. Thread
    growth moves from RAM to disk, still unbounded. Q12 (driver coexistence) comes back off
    the flag list and onto the frontier.

- **Q9 — The orchestrator is a general assistant** — it answers any non-geopolitical turn
  from its own knowledge; `expert` is the specialist it delegates to. Not meta-only (B), and
  no UI marking of sourceless answers (C). It gets **its own prompt and its own config/doc**,
  separate from the expert's — `app/src/agents/orchestrator/prompts.py` and `config.py`,
  matching this repo's rule that all of an agent's prompt text lives in its own `prompts.py`.
  _(rationale: user's call — this is the product as described from the start: a conversational
  agent that recognises geopolitical questions and hands them to a grounded specialist.)_
  - Challenged on: `ANSWER_SYSTEM_PROMPT` ("Treat your own background knowledge as
    unavailable") and `README.md` ("there is no degraded or fabricated answer") become false
    at the system level; and "answers everything else" is unbounded scope on a deployment with
    one shared password and a rate limit tuned for expensive research calls. → **Held.** The
    separate orchestrator prompt/config is the user's answer to the first half: the two
    epistemics live in two files rather than contradicting each other in one.
  - Consequences: cited and uncited answers are visually identical, so a misroute is silent —
    **Q5 becomes load-bearing**. `README.md` must be rewritten to describe two answer paths;
    carried as a release deliverable, not an open question. No refusal boundary on the
    general-assistant branch — accepted risk for the dev phase.

- **Q2 — Router mechanism: classifier node + conditional edge (Shape 1)** — one structured
  classification call, then a plain `add_conditional_edges` fork: `geopolitical -> expert`,
  `other -> chat`. Not a `create_react_agent` tool-calling orchestrator.
  _(rationale: the routing decision becomes a value in state that a unit test can assert,
  which is the only handle on Q5 given misroutes are now silent; and it matches this repo's
  character of explicit graphs with no hidden fallbacks.)_
  - Challenged on: it forecloses multi-hop research — the orchestrator hands off once and never
    sees what came back, so "search, read, refine, search again" needs the orchestrator rebuilt
    later; `create_react_agent` would have had it for free and costs no new dependency.
  - Consequences: one extra LLM call on every turn (mitigable with `TAG_NOSTREAM` for the
    stream, not for the cost). `_astream_answer` must be rewritten either way. Opens the
    nest-vs-flatten structural choice and the boundary-payload question (Q10).

- **Q10 — The orchestrator rewrites the turn into a standalone query** — the classifier's
  structured output carries both the route and a self-contained query, e.g.
  `{destination: "geopolitical", standalone_query: "What is happening in Poland?"}`. The expert
  still receives one plain string and its state stays `{query, sources, answer}` — no new node,
  no extra model call, no message history inside the expert.
  _(rationale: follow-ups actually work, and the expert stays exactly as simple as specified.)_
  - Challenged on: under the raw-turn answer, threads would have helped only the chat branch
    while the expert kept erroring on fragments — contradicting the reason Q1b was adopted.
    → **Revised** from "raw turn" to "rewrite in the classifier call."
  - Consequences: the rewrite is a second silent failure mode — a bad rewrite sends the expert
    after the wrong topic and the user never sees the rewritten string. Routing and rewriting
    share one model call, so their errors are correlated. Mitigation to decide in Q4: surface
    the rewritten query in an SSE progress frame. Conversation history reaches the classifier,
    never the expert.

- **Q11 — The expert stays its own compiled graph, nested as a node** — the orchestrator
  graph adds the compiled `expert` graph via `add_node`, rather than flattening the expert's
  two nodes into one graph or sharing node functions across two wirings.
  _(rationale: user's call — the expert remains a sealed unit that still runs standalone in
  LangGraph Studio, and `langgraph.json` and `CLAUDE.md` keep describing it accurately.)_
  - Challenged on: nesting drops the expert's tokens from the stream unless `subgraphs=True`,
    and that flag changes the emitted shape to `(namespace, data)`, breaking `_astream_answer`'s
    unpacking. → **Objection weakened by verification**: `test_api.py:226` executes the real
    loop over a real graph, so an empty stream is catchable in CI once that test points at the
    orchestrator graph. Held.
  - Consequences: `_astream_answer` is rewritten to pass `subgraphs=True` and handle
    namespace-prefixed events for both the nested expert path and the top-level chat node.
    Progress-frame inference, which the API does itself, becomes namespace-aware.
    `test_api.py:226` must be repointed at the orchestrator graph.

- **Q13 — Sticky browser-minted `thread_id`, plus a "New chat" button** — the frontend
  generates a UUID, persists it (localStorage), and sends it on every request; a button mints
  a fresh one. No login, so this is the only identity available.
  _(rationale: user's call — it feels like a real chat app and gives the user the one escape
  hatch they'd otherwise lack.)_
  - Challenged on: PENDING — with `InMemorySaver`, a server restart leaves the browser holding
    an id the server has never seen. The screen still shows the old conversation while the
    model has no memory of it — a worse illusion than a thread that dies with the tab.
    Also pending: whether history sent to the model is capped.
  - Consequences: `{query}` becomes `{query, thread_id}`; frontend gains persistence and a
    button; unbounded history growth per thread and unbounded thread accumulation in RAM.

- **Q12a — One driver; `prompt_logs` and `database.py` are deleted** — Postgres exists in
  this app for the checkpointer and nothing else. `asyncpg` is dropped; `psycopg` arrives with
  `langgraph-checkpoint-postgres` and is the only Postgres driver.
  _(rationale: user's call — "postgres for now only for checkpointer"; no second pool, no
  split data layer, and no feature kept alive just because it exists.)_
  - Challenged on: it deletes the only SQL-queryable record of what users actually ask, which
    is the natural raw material for the Q5 routing eval. → objection is **weak and stated as
    such**: Phoenix already captures full prompts and responses including failed runs, so the
    only real loss is IP-to-query association.
  - Consequences: `api.py` loses its `database` import, both lifespan calls and the `log_run`
    call; `database.py` and `test_database.py` are deleted; nine patch sites in `test_api.py`
    and three assertions go with them; `pyproject.toml` drops `asyncpg`.
    `_resolve_client_id` stays (rate limiting uses it). `README.md`, `CLAUDE.md`, `AGENTS.md`
    and `.github/copilot-instructions.md` all document `prompt_logs` and must be rewritten.
    Best done as its own commit, not folded into the orchestrator work.

- **Q14 — History sent to the model is capped at the last 10 turns** — conversation state
  keeps growing, but only a trailing window is passed to the orchestrator's model call.
  _(rationale: user's call — bounded cost per turn, cheap now, awkward to retrofit later.)_
  - Challenged on: PENDING — a turn *count* is a weak proxy for size. `ANSWER_LLM_SETTINGS`
    allows `max_output_tokens=16_384` (`agents/expert/config.py`), so ten assistant turns can
    be a very large payload; a character/token budget, or storing only short summaries of
    expert answers, bounds cost far more reliably than counting turns.
  - Consequences: the orchestrator's config gets a history-window constant (its own
    `config.py`, per this repo's hardcoded-dataclass rule).

- **Q12b — Postgres is required; no in-memory fallback** — with `DATABASE_URL` unset the app
  does not start. There is no degraded threads-in-RAM mode.
  _(rationale: user's call — logging is gone, so there is no half-working mode left worth
  supporting, and it matches this repo's hard-error, no-silent-fallback character.)_
  - Challenged on: PENDING — enforce it at the *API* layer, not at import time.
    `graph.py` compiles at module scope and `tests/unit_tests/test_api.py:257` calls
    `build_graph()` directly, so a checkpointer that opens a connection during construction
    would make `make test` and `langgraph dev` both require a running Postgres.
    Suggested shape: `build_graph(checkpointer=None)` — construction takes the checkpointer as
    an argument, the API lifespan requires `DATABASE_URL` and passes a real one, and Studio and
    unit tests pass none. Keeps "graph.py constructs and never runs" intact.
  - Consequences: `api.py:59-61`'s `if db_url:` guard becomes a hard requirement;
    `.setup()` must run once at startup to create the checkpointer tables; README/compose docs
    gain "Postgres is required".

- **Q5 — No routing evaluation this release** — no labelled query set, no accuracy test.
  Misroutes are found, if at all, by reading Phoenix traces by hand.
  _(rationale: user's call — dev phase, few users, and the boundary cases are not yet known.)_
  - Challenged on: PENDING — Shape 1 was chosen over a tool-calling agent *because* it makes
    the route a plain assertable value, at the price of multi-hop research. Option A leaves
    that purchase unused. Also pending: whether the classifier prompt at least carries a
    "when in doubt, choose geopolitical" bias, which costs one sentence.
  - Consequences: the Q9 accepted risk stands unmitigated — a misrouted geopolitical question
    returns a fluent, uncited answer indistinguishable from a cited one, and nothing counts how
    often it happens. Carried as the release's largest known risk.

- **Q5b — The classifier prompt stays neutral** — no "when in doubt, choose geopolitical"
  bias. The model decides each turn on its own.
  _(rationale: user's call, consistent with Q5: no routing machinery this release.)_
  - Challenged on: covered by the Q5 challenge; the bias was offered as a one-sentence
    mitigation and declined.
  - Consequences: ambiguous questions like "is Taiwan a country?" may be answered from
    parametric knowledge with no sources. Reinforces the Q9 accepted risk.

- **Q12c — `build_graph(checkpointer=None)`; the requirement lives in the API** — construction
  takes the checkpointer as an argument and opens no connection. The API lifespan requires
  `DATABASE_URL`, builds the Postgres saver and passes it in; `langgraph dev` and unit tests
  pass none and keep working with no database.
  _(rationale: user's call — `make test` must keep passing without Postgres, and the real app
  still hard-requires it.)_
  - Consequences: preserves "graph.py constructs and never runs"; `test_api.py:257`'s direct
    `build_graph()` call keeps working unchanged; `.setup()` runs in the API lifespan only.

- **Q4 — The "Searching..." frame is emitted only on the expert branch** — the API stops
  yielding `SEARCH_PROGRESS` unconditionally at the start of a run and emits it only once the
  route is known to be geopolitical. Chat turns get no search frame. The rewritten
  `standalone_query` is not surfaced to the user.
  _(rationale: user's call — the current frame is simply false on a chat turn, and the honest
  fix is not to send it.)_
  - Challenged on: with nothing emitted until the classifier returns, every turn would open
    with dead air where a frame used to appear instantly. → **Revised**: a neutral
    `THINKING_PROGRESS` frame is emitted immediately, and `SEARCH_PROGRESS` follows only on the
    expert branch. Three progress constants in `api.py` instead of two.
  - Consequences: progress inference in `api.py` becomes route-aware, so `_astream_answer` must
    tell the caller which branch ran — it currently yields only text. The Q10 mitigation
    (showing the rewritten query) is declined, so a bad rewrite stays invisible.

## Design tree

- **What the next release optimizes for** — SETTLED (Q1): orchestrator, dev phase.
  - **Release scope** — SETTLED (Q1b, revised): orchestrator + threads + PostgresSaver.
    - Orchestrator answering scope — SETTLED (Q9): general assistant
    - Router mechanism — SETTLED (Q2): classifier node + conditional edge
    - Orchestrator->expert boundary payload — SETTLED (Q10): classifier rewrites to a standalone query
    - `thread_id` issuance, lifetime, scope — SETTLED (Q13): sticky + New chat button
    - Expert nesting vs flattening — SETTLED (Q11): nested compiled subgraph
    - API/SSE contract & progress frames — SETTLED (Q4): search frame on the expert branch only
    - Driver + prompt_logs removal — SETTLED (Q12a): one driver, `database.py` deleted
    - DB required vs optional at startup — SETTLED (Q12b): required, no fallback
    - Where the requirement is enforced — SETTLED (Q12c): `build_graph(checkpointer=None)`
    - Classifier prompt bias — SETTLED (Q5b): neutral, no bias
    - History window sent to the model — SETTLED (Q14): last 10 turns
  - Routing correctness / misroute detection — SETTLED (Q5): nothing this release
  - Answer quality (model, retrieval, source policy) — DEFERRED (Q6, Q7), not this release
  - Evaluation harness — PRUNED (Q5): deferred past this release
  - Ops/product (auth, i18n, cost caps) — OPEN (Q8), long-term

## Current frontier (open questions)

_Empty — every live branch visited._

## Carried as flags, not decisions

**Deferred, not rejected**

- **Q6 — Retrieval and source policy.** 28 allow-listed domains, all English/US-UK, three fixed
  Brave batches, no non-English sources. Untouched this release. The classifier's
  `standalone_query` rewrite is the *only* query rewriting that ships.
- **Q7 — Model and cost budget.** `gpt-4o-mini` at `max_output_tokens=16_384` stays for the
  expert; the orchestrator's own model is an implementation-time choice in its `config.py`.
  No per-request cost cap.
- **Routing evaluation (Q5).** No labelled query set, no accuracy test. Revisit when real
  traffic shows what the boundary cases actually are — Phoenix traces are the source material.
- **Multi-hop research.** Foreclosed by Q2's Shape 1: the orchestrator delegates once and never
  reacts to what the expert returned. Adding it later means rebuilding the orchestrator around
  a tool-calling agent.

**Accepted risks, shipping anyway**

- **Silent misroutes (Q9 + Q5 + Q5b).** A geopolitical question routed to `other` returns a
  fluent, confident, uncited answer that looks identical to a cited one. Nothing detects it and
  nothing counts it. **This is the release's largest known risk** and it is the exact failure the
  product exists to prevent.
- **`thread_id` is an unauthenticated bearer token (Q1b, Q13).** Production is one shared HTTP
  Basic credential; no user owns a thread. Whoever holds an id reads that conversation. Low
  severity now, grows precisely as real users arrive.
- **Unbounded thread accumulation (Q1b).** Checkpoints persist in Postgres forever; nothing
  prunes or expires them.
- **A turn count is not a size budget (Q14).** Ten turns can be very large when an expert answer
  may run to 16k output tokens. A character budget would bound cost more reliably.
- **No refusal boundary (Q9).** The general-assistant branch will attempt code, medical, and
  legal questions. Accepted for the dev phase.
- **IP-to-query association is lost (Q12a).** Phoenix captures prompts and responses, including
  failures, but not the client address.
- **A bad rewrite is invisible (Q10 + Q4).** The `standalone_query` is never shown to the user,
  so a misunderstood follow-up produces a confidently-cited answer to a question nobody asked.

**Verify before implementation**

- `subgraphs=True` changes emitted events to `(namespace, data)`
  (`langgraph/pregel/main.py:2763-2767`). Confirm the exact shape for a **single** `stream_mode`
  against the installed version before rewriting `_astream_answer` — the existing comment above
  that loop warns about precisely this class of silent unpacking bug.
- `AsyncPostgresSaver.setup()` must run once before first use; decide whether that belongs in
  the API lifespan on every boot or in a one-shot migration step.

## Round log

### Round 1 — Q1: What is this app, and what is the next release optimizing for?
Posed. Lean: the orchestrator is the *second* most valuable thing, and which one wins
depends entirely on whether this is a product with users or a showcase of agentic architecture.

**User answered:** neither A/B/C/D as framed — *"in long term it will be using be real users,
but for now it is a development phase. Right now I just want to have 1 expert agent (which is
really simple) and I want to have orchestrator. Orchestrator will call expert if it will detect
political/geopolitical question, if question will be other it will handle it by itself."*
**Pushed back on** the orchestrator answering non-geopolitical turns from parametric knowledge
in the same UI — a misroute is silent, produces a fluent uncited answer, and nothing measures it;
and the router sees one turn with no history, so "and Poland?" is unclassifiable. → PENDING.

### Round 2 — Q1b: Hold / Narrow / Widen the orchestrator's release scope
Presented three shapes: **Hold** (orchestrator answers any non-geopolitical turn),
**Narrow** (orchestrator handles only meta turns; ambiguity biases toward sources),
**Widen** (accept that memory ships with the router). Lean was **Narrow** (moderate) —
same build cost as Hold, strictly better failure mode, keeps the release small.
**User answered: Widen** — *"I want thread and checkpointer."*
**Pushed back on** the checkpointer buying durability rather than the follow-up resolution
that motivated it, its `psycopg`-vs-`asyncpg` driver cost, and `thread_id` as an
unauthenticated bearer token behind one shared password. → PENDING.

### Round 3 — Q1b follow-up: how much of Widen ships now
Offered three ways to hold Widen: ① Postgres checkpointer as stated, ② thread_id +
`InMemorySaver` now with the backend deferred, ③ port `database.py` off `asyncpg` to run one
driver. Lean was ②. **User answered: ②** — "hold the thread, defer the backend."
No further pushback (already challenged once on Q1b; this *is* the revision). Verified
afterwards that the backend runs single-process, so `InMemorySaver` is correct here rather
than merely convenient.

### Round 4 — Q9: What may the orchestrator answer by itself?
Offered A (general assistant), B (meta-only, ambiguity biases toward sources), C (answer
freely but render sourceless answers visibly differently). Noted that the Q1b threads decision
had already killed my earlier "follow-ups are unclassifiable" argument for B. Lean was **C**
(moderate) — keeps A's product, converts A's silent failure into a visible one for one CSS
state and one SSE field. **User answered: A.**
**Pushed back on** the now-false product claim in `ANSWER_SYSTEM_PROMPT` and `README.md`, and
on unbounded general-chatbot scope. → PENDING.
**User held A**, adding that the orchestrator gets its own prompt and its own config/doc.
Recorded: `README.md` rewrite becomes a release deliverable; no refusal boundary, accepted risk.

### Round 5 — Q2: How does the orchestrator decide?
Offered Shape 1 (classifier + conditional edge) vs Shape 2 (`create_react_agent` with `expert`
as a tool), then expanded both on request with Context7 + installed-source verification.
Surfaced three facts that changed the question: nested-subgraph tokens are dropped unless
`subgraphs=True` (which breaks the current unpacking), `TAG_NOSTREAM` cleanly hides a
classifier call from the stream, and `create_react_agent`'s nodes are `agent`/`tools` so the
`api.py:200` filter breaks either way. Also surfaced a third variant: flatten the expert's
nodes into one graph and avoid namespaces entirely.
Lean was Shape 1 (moderate→strong). **User answered: Shape 1.**
**Pushed back on** the multi-hop foreclosure. → PENDING.
**User accepted** the multi-hop foreclosure implicitly by choosing Shape 1 and moving on.

### Round 6 — Q10: What does the expert actually receive?
Offered A (raw turn), B (orchestrator rewrites the follow-up into a standalone query, riding
the classifier's structured call), C (full message history into the expert). Lean was **B**
(strong). **User answered: A.**
**Pushed back on** the tension with Q1b — threads were adopted to fix cold follow-ups, and
under A the expert branch's follow-ups stay cold. → PENDING.
**Re-posed in plain language with a worked chat transcript. User revised to ③ = option B:**
the app rewrites the question before searching.

### Round 7 — Q11: Where do the expert's two steps live?
Offered 1 (expert stays its own graph, nested as a node), 2 (one flat four-node graph), 3
(share node functions, keep both wirings). Lean was **2** (moderate) — no nesting means no
streaming rework. **User answered: 1.**
**Pushed back on** the streaming rewrite, then **checked the test suite and weakened my own
objection**: `test_api.py:226` really does execute `_astream_answer` against a real graph with
a fake chat model, so the "empty stream" failure is catchable in CI. Held.

### Round 8 — Q13: When does a conversation start and end?
Offered A (thread per tab), B (sticky in localStorage), C (sticky + a "New chat" button), and
flagged two things none of them solve: unbounded history growth per turn and unbounded thread
accumulation in `InMemorySaver`. Lean was **C plus a turn cap** (moderate).
**User answered: C.**
**Pushed back on** the restart-amnesia illusion, and asked for a decision on the history cap.
-> PENDING.

### Round 9 — Q13 follow-up: the restart-amnesia problem
Offered (1) accept it, (2) fresh id per page load, (3) detect and tell the user, plus a
yes/no on capping history at ~10 turns. **User answered neither — they reversed Q1b instead:**
*"Use PostgresSaver for checkpointer."* That dissolves the objection at the source rather than
mitigating it, and it is a better argument for durability than the one offered in round 3.
Q1b re-settled as Postgres; Q12 (driver coexistence, required-vs-optional DB) re-opened.
The history cap is still undecided and stays on the frontier.

### Round 10 — Q12: What happens when there's no database?
Offered A (Postgres required, hard error without it) vs B (Postgres if present, memory if not),
plus a side choice of one driver vs two. Lean was **A, one driver** (moderate).
**User answered the driver half:** one driver — and went further: *"let's also remove database
for saving some stuff from api. I want postgres for now only for checkpointer."* So
`prompt_logs`, `database.py` and `asyncpg` all go.
**Pushed back on** losing the only SQL-queryable record of real user queries, then withdrew
most of it after checking: Phoenix already captures prompts and responses including failures.
**Q12b (required vs optional) is still unanswered**, as is the history cap.

### Round 11 — leftovers: DB required-vs-optional, and the history cap
**User answered the cap:** send only 10 turns. On the first question they replied "I have
phoenix for tracing" — which addresses the withdrawn observability objection from round 10
rather than the required-vs-optional startup question, so **Q12b remains open**.
**Pushed back on** the cap being a turn count rather than a size budget, given the expert's
`max_output_tokens=16_384`. -> PENDING.

### Round 12 — Q12b: Should the app refuse to start without a database?
Re-asked after round 11 answered a different question. **User answered: A** — required, no
in-memory fallback. **Pushed back on** *where* the requirement is enforced: making it
import-time would drag Postgres into `make test` and `langgraph dev`, so the checkpointer
should be a `build_graph()` argument with the requirement living in the API lifespan.

### Round 13 — Q5: How would you know the router got it wrong?
Offered A (nothing this release; read Phoenix by hand), B (30-50 labelled queries + an accuracy
test), C (prompt bias toward the expert, measure nothing). Lean was **B plus C's bias**
(moderate). **User answered: A.**
**Pushed back on** the coherence cost: Shape 1 was bought with multi-hop capability precisely
because it makes the route testable, and A never spends it. Asked whether the one-sentence
prompt bias goes in regardless. -> PENDING.

### Round 14 — two leftovers, re-posed in plain language
Asked as a plain yes/no pair: (1) should the classifier prefer searching when unsure, and
(2) should `make test` require Postgres. **User answered "both B"**: no bias sentence in the
classifier prompt, and tests keep working without a database. Both recorded; the bias had
already been challenged once under Q5, so no second pushback.

### Round 15 — Q4: the "Searching..." message
Offered A (emit it only when actually searching), B (neutral "Thinking..." always), C (show the
rewritten query, making the Q10 rewrite visible). Lean was **C**. **User answered: A.**
**Pushed back on** the dead air at the start of every turn while the classifier runs. -> PENDING.
**User accepted the revision:** a neutral "Thinking..." frame fires immediately, then
"Searching and reading sources..." only when the expert branch runs.

### Round 16 — Q8: what is explicitly not in this release?
Presented the non-goals and accepted risks accumulated across the session as one list.
**User confirmed the list unchanged.** Frontier empty; session closed.

