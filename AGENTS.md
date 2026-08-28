# AGENTS.md

Guidance for coding agents working in this repository. After any codebase
change, update `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md`
together and keep their facts consistent.

## Repository Layout

The maintained application lives under `app/`; the root entrypoint, Dockerfile,
and requirements export are compatibility files. `app/src/` is the Python
import root. Shared infrastructure contains `config.py` (environment/model
settings), `models.py` (Candidate, Source, SourcePolicy, PipelineError types),
`search.py` (policy-parameterized Brave/fetch boundary), `llm.py` (OpenAI
boundary), and delivery modules `api.py` and `database.py`.

Each agent is under `app/src/agents/<name>/` with `graph.py`, `state.py`,
`config.py`, `prompts.py`, a `consts/` package for static data, and one
module per graph node in `nodes/`. Shared modules never import agents; only
`api.py` names `agents.expert`. The old `nodes/`, `planning.py`,
and `render.py` modules are gone.

Static, hardcoded agent data (currently just editorial policy) lives under
`consts/`, one module per concern — e.g. `agents/expert/consts/sources.py`
holds the domain allow-list. `config.py` stays for tunable settings
(dataclasses like `LLMSettings`); `consts/` is for data that's effectively
fixed reference material, not a knob anyone would flip per environment.

`prompts.py` holds every prompt constant for that agent, one per
node/purpose (e.g. `agents/expert/prompts.py`'s `ANSWER_SYSTEM_PROMPT`),
imported into the node that uses it — prompt text is never inlined in a
node module.

Config is hardcoded dataclasses, not env-parsed getters. Shared `config.py`
defines `LLMSettings` (model, temperature, timeout_seconds, max_output_tokens) and a
`DEFAULT_LLM_SETTINGS` instance. An agent's `config.py` holds its own
pipeline tuning as plain dataclasses/constants — e.g.
`agents/expert/config.py`'s `ANSWER_LLM_SETTINGS` (a per-node `LLMSettings`
override) and `RETRIEVAL` (a `RetrievalSettings` with `fetch_candidates`/
`keep_sources`) — edited directly in code, passed explicitly into node calls
(`llm.astream_text(..., settings=...)`), never read from the environment.
Editorial policy (domains, batching, paywalls) stays in
`consts/sources.py`.

`app/src/tracing.py` is a shared, optional tracing boundary: `init_tracing()`
registers self-hosted Arize Phoenix span export when
`PHOENIX_COLLECTOR_ENDPOINT` is set, is idempotent, and never raises — an
unreachable collector must never fail a request. `api.py`'s lifespan and
`agents/expert/graph.py` (at module scope, for `langgraph dev`) each call it
once.

## Architecture

The expert graph is exactly:

```text
START -> search_and_fetch -> answer -> END
```

Its `PipelineState` in `app/src/agents/expert/state.py` has exactly `query`,
`sources`, and `answer`, with no reducers. The expert editorial policy is one
flat English allow-list in `agents/expert/consts/sources.py`, passed to
shared search
as `SourcePolicy`. Search makes exactly three concurrent Brave batches, then
fetches and extracts allow-listed pages with `trafilatura`. Only fetched article
text reaches the single streamed plain-text LLM call. Search outages, no usable
sources, and model failures are hard errors; there are no deterministic or
degraded fallbacks. Runtime configuration carries only optional `thread_id`.

## API and Frontend

`app/src/api.py` exposes `GET /api/health`, `POST /api/run_pipeline`, and
`POST /api/run_pipeline/stream`, plus `/` for the static English frontend.
Requests contain only `query`, normalized and limited to 2,000 characters.
Known failures map to 422 (no sources), 503 (search unavailable), and 502 (LLM).
SSE events remain `progress`, `token`, `result`, and `error`. Markdown output
is sanitized in the browser before insertion.

Development ports are frontend 8082, backend 3001, PostgreSQL 55432, and
Phoenix 6006 (loopback-bound, dev override only — base and prod compose
publish no Phoenix port). Production compose adds health checks, restart
policies, TLS mounting, and nginx basic authentication. `app/langgraph.json`
exposes the graph as `expert`.

## Commands

Run Python commands from `app/`: `uv sync --locked --dev`, `make test`,
`make integration_tests`, `make lint`, and `make format`. Use `langgraph dev`
from `app/` to drive the graph in Studio.
CI runs `uv sync --locked --dev` from `app/` on Python 3.11 and does not use
the root requirements file; compose builds `./app` and `./frontend`.

Required variables are `OPENAI_API_KEY` and `BRAVE_SEARCH_KEY`; optional
settings include database, CORS, API rate-limit, logging, frontend path, and
LangSmith tracing variables. Model/timeout/token knobs are hardcoded
`LLMSettings` dataclasses in code, not environment variables — see
`config.py` and `agents/expert/config.py`. `PHOENIX_COLLECTOR_ENDPOINT` and
`PHOENIX_PROJECT_NAME` are the Phoenix tracing switches; unset means no
tracing, and exported spans carry full prompt/response text with no
redaction.

There is exactly one `.env`, at the repo root. `config.py` resolves it by
absolute path regardless of working directory, so the API, tests, and
`langgraph dev` (via `app/langgraph.json`'s `env: "../.env"`) all read the
same file Compose's `env_file: .env` uses; there is no separate `app/.env`.
Compose derives `DATABASE_URL` from `POSTGRES_PASSWORD` automatically, so
prompt-log DB writes are on by default.

## Change Guidance

- Keep state flat and have nodes return partial dictionaries without mutation.
- Put sequencing in graph edges; do not reintroduce removed pipeline concepts.
- Preserve the shared-to-agent import direction and policy parameterization.
- Add focused tests under `app/tests/` and keep explicit module imports where
  package `__init__` files re-export functions.
- Do not modify `.env` files, commit secrets, or add top-level Python modules.
