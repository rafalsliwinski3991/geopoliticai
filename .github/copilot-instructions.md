# Copilot Instructions

After every codebase change, update `AGENTS.md`, `CLAUDE.md`, and this file
together. The maintained application is under `app/`; the root Dockerfile and
requirements-export file are compatibility files (the old root `main.py` CLI
shim is gone). CI runs `uv sync --locked --dev` in `app/` and does not
reference root requirements.

Shared modules under `app/src/` provide environment/model config, shared models
and errors, policy-parameterized Brave/fetch/extraction, OpenAI access, API
delivery, and an optional tracing boundary. There is no `database.py` or
`prompt_logs` persistence path; Postgres is used only for the LangGraph
checkpointer. The app declares `psycopg[binary]` directly, so no system `libpq`
installation is required. Agent packages under
`app/src/agents/<name>/` contain graph, state, hardcoded config, prompts, static
`consts/`, and node modules. Shared modules never import agents; the API names
`agents.orchestrator`, whose expert node invokes `agents.expert`.

Repository-local Codex skills live under `.codex/skills/`; `.codex/skills/grill-me`
provides a one-question-at-a-time adversarial design-review workflow and
persists its session artifact under `docs/brainstorming/`.
OpenCode also loads the Phoenix skills under `.agents/skills/` through the
`skills.paths` entry in `opencode.jsonc`: `phoenix-cli`, `phoenix-evals`, and
`phoenix-tracing`.

Config is hardcoded dataclasses, not env-parsed getters. Shared `config.py`
defines `LLMSettings` and `DEFAULT_LLM_SETTINGS`; agent config holds per-node
overrides and pipeline sizing, passed explicitly into calls. Prompts belong in
the agent's `prompts.py`, and fixed editorial data belongs in `consts/`.

The orchestrator graph is:

```text
START -> classify -> expert -> END
                  \-> chat   -> END
```

Geopolitical turns go to the nested expert; other turns go to the
orchestrator's own chat branch, which has no source citations. The expert is
also separately exposed in Studio and remains:

```text
START -> search_and_fetch -> answer -> END
```

The expert uses exactly three Brave batches, allow-listed extraction with
trafilatura, and one streamed plain-text model call. Failures are hard errors;
there are no degraded expert fallbacks. Invoke the expert from inside its
orchestrator node, not via `add_node`, because the state schemas do not share a
key and the child result can otherwise be silently discarded.

The API accepts exactly `{query, thread_id}`, normalizes and caps the query at
2,000 characters, and requires a shape-validated thread id. API startup
requires `DATABASE_URL`, opens the Postgres pool, runs
`AsyncPostgresSaver.setup()`, and compiles the orchestrator with the persistent
checkpointer. `build_graph()` still defaults to no checkpointer for tests and
`langgraph dev`.

`api.py` runs the graph with
`stream_mode=["updates", "messages"]` and `subgraphs=True`, unpacking
`(namespace, mode, data)` and forwarding only answer-node (`answer` or `chat`)
`AIMessage` text. Progress is Thinking, Searching only on the expert branch,
then Writing. Pipeline failures are SSE `error` frames with known statuses 422,
503, and 502 (500 is the generic fallback). The frontend sanitizes
Markdown, stores a sticky thread id in `localStorage`, includes it in each
request, and has a **New chat** button for a fresh thread.
`_generate` caps emitted output at 50,000 characters but drains an over-limit
upstream stream before emitting the capped result so checkpoint writes can
complete.

The base Compose file gives Postgres a `pg_isready` healthcheck. The backend
depends on Postgres with `condition: service_healthy` and on Phoenix with
`condition: service_started`. Development ports are frontend 8082, backend
3001, PostgreSQL 55432, and Phoenix 6006 through the loopback-bound override.
Production adds health checks, restart policies, TLS mounting, and nginx Basic
Auth covering both `/` and `/api/`. `AUTH_REQUIRED=true` fails closed when
credentials are missing, while local development remains unauthenticated.
Phoenix data is kept in the `phoenix_data` volume and its host port is only
published by the loopback-bound development override.

Run `uv sync --locked --dev`, `make test`, `make integration_tests`, and
`make lint` from `app/`; use `langgraph dev` to drive either graph in Studio.
Nodes return partial state dictionaries without mutation, tests should use
explicit module imports when package initializers re-export functions, and no
`.env` or secrets should be changed.

There is exactly one `.env` at the repo root, read by the API, tests,
`langgraph dev` (`app/langgraph.json`'s `env: "../.env"`), and Compose's
`env_file: .env`; `config.py` resolves it by absolute path. There is no
separate `app/.env`. `OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`, and `DATABASE_URL`
are required by the API; Compose derives the database URL from
`POSTGRES_PASSWORD`. Phoenix tracing is optional, env-gated, idempotent, and
never raises; exported spans contain full prompt/response text without
redaction. CORS origins and rate limits are hardcoded in `api.py`.
