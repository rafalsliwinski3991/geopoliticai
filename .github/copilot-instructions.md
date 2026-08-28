# Copilot Instructions

After every codebase change, update `AGENTS.md`, `CLAUDE.md`, and this file
together. The maintained application is under `app/`; root files are
compatibility entrypoint, Docker, and requirements-export files. CI runs
`uv sync --locked --dev` in `app/` and does not reference root requirements.

Shared modules under `app/src/` provide environment/model config, shared models
and errors, policy-parameterized Brave/fetch/extraction, OpenAI access,
delivery, and an optional tracing boundary (`tracing.py`). Agent packages
under `app/src/agents/<name>/` contain graph, state, an agent-level
`config.py`, a `prompts.py` with every prompt constant for that agent, a
`consts/` package for static data like source policy (expert's
`consts/sources.py`), and node modules. Shared modules never import agents;
only the API names `agents.expert`.

Config is hardcoded dataclasses, not env-parsed getters: shared `config.py`
defines `LLMSettings` and `DEFAULT_LLM_SETTINGS`; an agent's `config.py`
holds its own per-node overrides and pipeline sizing as plain dataclasses
(e.g. expert's `ANSWER_LLM_SETTINGS`, `RETRIEVAL`), passed explicitly into
calls rather than read from the environment. `api.py` follows the same rule for
`ALLOWED_ORIGINS`, `RATE_LIMIT_REQUESTS`, and `RATE_LIMIT_WINDOW_SECONDS`.

`tracing.py`'s `init_tracing()` registers self-hosted Arize Phoenix span
export when `PHOENIX_COLLECTOR_ENDPOINT` is set, is idempotent, and never
raises — telemetry failures must never fail a request. It's called from the
API lifespan and `agents/expert/graph.py` module scope
(for `langgraph dev`). Compose runs a `phoenix` service with a `phoenix_data`
volume and no published host port outside the dev override's loopback
mapping.

The expert graph is:

```text
START -> search_and_fetch -> answer -> END
```

State has exactly `query`, `sources`, and `answer`, with no reducers. The expert
policy is English-only and search performs exactly three Brave batches followed
by allow-listed page extraction with trafilatura. One streamed plain-text LLM
call produces the answer. Search, source, and LLM failures are hard errors;
there are no deterministic fallbacks. `app/langgraph.json` exposes `expert`.

The API accepts only `{query}`, normalizes and caps it at 2,000 characters, and
provides one SSE route; pipeline failures arrive as an SSE `error` frame. All
error types are `PipelineError` subclasses in `models.py`, each with its own
`status` ClassVar. The
frontend sanitizes Markdown before `x-html`.

Run `uv sync --locked --dev`, `make test`, `make integration_tests`, and
`make lint` from `app/`; drive the graph in Studio with `langgraph dev`.
Nodes return partial state dictionaries without mutation, tests should use
explicit module imports when package initializers re-export functions, and no
`.env` or secrets should be changed.

There is exactly one `.env`, at the repo root, read by the API, tests,
`langgraph dev` (`app/langgraph.json`'s `env: "../.env"`), and Compose's
`env_file: .env` alike; `config.py` resolves it by absolute path. There is
no separate `app/.env`. Compose derives `DATABASE_URL` from
`POSTGRES_PASSWORD` automatically, so prompt-log DB writes are on by
default. `prompt_logs` has no geolocation column; `init_pool` drops a legacy
`location` column on every start, irreversibly. `log_run` is the only writer:
one insert per successful run, silent on failure.
