# CLAUDE.md

Guidance for Claude Code working in this repository. After any codebase change,
update `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` together.

The maintained application is under `app/`; root files are compatibility
entrypoint, Docker, and requirements-export files. Shared modules in
`app/src/` provide environment/model config, shared models/errors, a
policy-parameterized Brave and trafilatura search boundary, the OpenAI boundary,
API/database delivery, and an optional, env-gated tracing boundary.
Agent-specific code is under `app/src/agents/<name>/`; shared modules never
import an agent. All of an agent's prompt text lives in its own
`prompts.py`, one constant per node/purpose, imported by that node — not
inlined in the node module. Config is hardcoded dataclasses, not env-parsed getters:
shared `config.py` defines `LLMSettings` (model/temperature/timeout/max_output_tokens)
and a `DEFAULT_LLM_SETTINGS` instance; an agent that wants different values
for one node builds its own `LLMSettings(...)` (and any other pipeline
sizing, e.g. `agents/expert/config.py`'s `RetrievalSettings`) in its own
`config.py` and passes it through explicitly — no env var reads it.

The expert graph is `START -> search_and_fetch -> answer -> END`. Its state has
exactly `query`, `sources`, and `answer`, without reducers. The expert policy is
an English allow-list passed as `SourcePolicy`; search performs exactly three
Brave batches and only extracted allow-listed page text reaches one streamed
plain-text model call. Failures are hard errors with no degraded fallback.
`graph.py` constructs and never runs: `api.py`'s `_astream_answer` owns the run
loop, over `graph.astream(..., stream_mode="messages")` filtered on
`metadata["langgraph_node"] == "answer"` and `isinstance(message, AIMessage)`,
with `BaseMessage.text()` flattening content blocks. Progress frames are
inferred by the API rather than read off graph events.

The API accepts only `{query}` (normalized, max 2,000 characters) and serves
one SSE endpoint; pipeline failures are reported in an SSE `error` frame, not
as an HTTP status. Every pipeline failure is one `PipelineError` subclass
defined in `models.py`, `LLMInvocationError` included, and each class carries
the HTTP `status` a delivery layer reports for it — there is no lookup table.
Its CORS origins and rate limit follow the same hardcoding
rule as `LLMSettings`: `ALLOWED_ORIGINS`, `RATE_LIMIT_REQUESTS`, and
`RATE_LIMIT_WINDOW_SECONDS` are constants in `api.py` and read no environment
variable.
The English frontend sanitizes rendered Markdown. LangGraph configuration names
the graph `expert`.

From `app/`, use `uv sync --locked --dev`, `make test`, `make integration_tests`,
`make lint`, `make format`, and `langgraph dev`. CI uses the app lockfile and
does not reference
root requirements; compose builds `./app` and `./frontend`.

There is exactly one `.env`, at the repo root. `config.py` resolves it by
absolute path regardless of working directory, `app/langgraph.json`'s `env`
field points at `../.env`, and Compose's `env_file: .env` reads the same
file; there is no separate `app/.env`. Compose wires `DATABASE_URL` from
`POSTGRES_PASSWORD` automatically, so prompt-log DB writes are on by
default whenever Postgres runs alongside the backend. `prompt_logs` carries
no geolocation: `init_pool` drops a legacy `location` column on every start,
irreversibly, and `database.py` makes no outbound HTTP call. `log_run` is the
only writer — one insert after a successful run, silent on failure, so failed
runs are not recorded anywhere.

Compose also runs a `phoenix` service (self-hosted Arize Phoenix) on the
internal network with a `phoenix_data` volume; it publishes no host port
outside `docker-compose.override.yml`'s loopback-bound dev mapping.
`app/src/tracing.py` calls `phoenix.otel.register(...)` from the API
lifespan and `agents/expert/graph.py` module scope, and
never raises — an unreachable collector must never fail a request.
`PHOENIX_COLLECTOR_ENDPOINT` and `PHOENIX_PROJECT_NAME` are the only
switches; unset means no tracing, and full prompt/response content is
exported with no redaction by design.

Keep changes local, return partial state updates, preserve import direction, add
focused tests, avoid `.env` and secrets, and update all three guidance files for
every codebase change.
