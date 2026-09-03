# AGENTS.md

Any change anywhere in the repository must update `AGENTS.md`, `CLAUDE.md`, and
`.github/copilot-instructions.md` together. This repository uses OpenCode,
GitHub Copilot and the GitHub CLI (`gh`), Claude Code, and Codex. If a plugin,
skill, or other tool is added, removed, renamed, or changed, update the
Commands, Plugins, and other provider-column inventory tables in
`ai_tools_tables.md` in the same change. Inventory tables use one item-name
column followed by one `yes`/`no` column per provider.

@@
The Codex catalog includes the shared framework skill sets. Its `phoenix-cli`,
`phoenix-evals`, and `phoenix-tracing` packages are concrete project-local
copies converted to Codex-valid frontmatter, not symlinks.

The maintained application lives under `app/`; the root Dockerfile and
requirements export are compatibility files (the old root `main.py` CLI shim
is gone). `app/src/` is the Python import root. Shared infrastructure contains
`config.py`, `models.py`, `search.py`, `llm.py`, `tracing.py`, and `api.py`.
There is no `database.py` or `prompt_logs` persistence path: Postgres is used
only by the LangGraph checkpointer constructed by the API lifespan. The app
declares `psycopg[binary]` directly, so no system `libpq` installation is
required.

Repository-local Codex skills live under `.codex/skills/`. Claude's
`rs-brainstorming` workflow is a custom command under `.claude/commands/`.
Explicit
`$plan-from-brainstorm`, `$improve-plan`, and `$implement-plan` skills are the
Codex equivalents of the three Claude `rs-` planning commands; they use this
repository's `explorer`, `critic`, and `builder` roles rather than
Claude-specific agent types. Claude's `rs-brainstorming` classifies work as
spike, bounded, or architectural. Its architectural path uses a
similarity-grouped batch adversarial design-review workflow by default, persists
an artifact under `docs/brainstorming/`, and requires user approval before
`$plan-from-brainstorm`.
Claude's `rs-plan-from-brainstorm` right-sizes plans: minor, contained changes
receive lightweight scope, change, and validation steps with self-review;
coherent multi-file subsystem work receives a standard file-level task plan and
one correctness review; major or risky work receives ordered commits and three
subagent reviews before approval and `$implement-plan` handoff.
Claude's `rs-improve-plan` and `rs-implement-plan` preserve or infer that plan
tier. `rs-implement-plan` uses TDD for every behavior change: lightweight work
is direct implementation with self-review, standard work adds one correctness
review, and full work adds task audits and broad three-lens review; only
genuinely independent full-plan tasks may be delegated.
Claude's `rs-implement-plan-as-codex` is the Codex-plugin variant: all delegated
implementation and review work uses `/codex:rescue` with `gpt-5.6-terra` and high
effort, and it fails closed rather than falling back to a Claude agent or model.
The repository-local Codex `critic` agent is read-only and uses
`gpt-5.6-terra` with high reasoning effort.
The Codex catalog includes the shared framework skill sets and project-local
documentation, Phoenix, and planning skills. Its Phoenix packages are
concrete project-local copies converted to Codex-valid frontmatter, not
symlinks.
The project-local `docs-manage`, `docs-search`, and `fetch-url` skills manage
and query the Grounded Docs index or fetch a single page; they require Node.js
22 or newer and `npx`.
The canonical Phoenix sources remain under `.agents/skills/`; OpenCode loads
them through the `skills.paths` entry in `opencode.jsonc`, while Claude exposes
them through symlinks in `.claude/skills/`.
No external documentation MCP server is configured in the repository.

Each agent is under `app/src/agents/<name>/` with `graph.py`, `state.py`,
`config.py`, `prompts.py`, a `consts/` package for static data, and one module
per graph node in `nodes/`. Shared modules never import agents. The API names
`agents.orchestrator`; the orchestrator invokes `agents.expert` as a nested
compiled graph. The expert remains separately available in Studio. The old
top-level `nodes/`, `planning.py`, and `render.py` modules are gone.

Static, hardcoded agent data lives under `consts/`, one module per concern —
for example, `agents/expert/consts/sources.py` holds the domain allow-list.
`config.py` is for tunable settings such as `LLMSettings`; `consts/` is for
fixed reference material, not an environment knob. Every prompt constant lives
in that agent's `prompts.py`, one per node or purpose, and is imported by the
node that uses it.

Config is hardcoded dataclasses, not env-parsed getters. Shared `config.py`
defines `LLMSettings` (model, temperature, timeout, and token limit) and
`DEFAULT_LLM_SETTINGS`. `models.py` contains the source structures and the
`PipelineError` hierarchy: search-unavailable, no-sources, and model failures
carry HTTP statuses 503, 422, and 502; the base error defaults to 500. Agent
config contains
per-node overrides and pipeline sizing, passed explicitly into node calls and
never read from the environment. Editorial policy (domains, batching, and
paywalls) stays in `consts/sources.py`.

`app/src/tracing.py` is an optional tracing boundary: `init_tracing()`
registers self-hosted Arize Phoenix span export when
`PHOENIX_COLLECTOR_ENDPOINT` is set, is idempotent, and never raises. The API
lifespan and both graph modules call it where needed for API and Studio use.

## Architecture

The orchestrator graph is:

```text
START -> classify -> expert -> END
                  \-> chat   -> END
```

It classifies the latest turn and sends geopolitical questions to the nested
expert, while the `chat` branch answers other turns from the model's own
knowledge without source citations. The expert graph is unchanged:

```text
START -> search_and_fetch -> answer -> END
```

The expert state has exactly `query`, `sources`, and `answer`, with no
reducers. Its policy is one flat English allow-list passed as `SourcePolicy`.
Search makes exactly three concurrent Brave batches, then fetches and extracts
allow-listed pages with `trafilatura`; only fetched article text reaches its
single streamed plain-text LLM call. Search, source, and model failures are
hard errors with no degraded expert fallback.

The expert is invoked from inside the orchestrator's `expert` node, not passed
directly to `add_node`: the two state schemas share no key, and LangGraph can
silently run such a child on empty input and discard its output. `graph.py`
only constructs graphs. The orchestrator's `build_runtime_config` requires a
`thread_id`; the API builds a persistent `AsyncPostgresSaver` checkpointer at
startup and passes it to `build_graph`. Its Postgres pool uses autocommit,
`prepare_threshold=0`, and `dict_row`, then runs `checkpointer.setup()`.

The API stream drives the orchestrator with
`stream_mode=["updates", "messages"]` and `subgraphs=True`, unpacking
`(namespace, mode, data)` events. It emits a route event after classification
and filters streamed model messages to answer nodes (`answer` and `chat`),
`AIMessage`, and `BaseMessage.text()`. The UI progress sequence is Thinking,
then search only for the geopolitical branch, then Writing the answer.
`_generate` caps emitted output at 50,000 characters but drains an over-limit
upstream stream before emitting the capped result, allowing checkpoint writes
to complete.

## API and Frontend

`app/src/api.py` exposes `GET /api/health` and
`POST /api/run_pipeline/stream`, plus `/` for the static English frontend.
There is no synchronous HTTP route. Requests are exactly `{query, thread_id}`:
the query is normalized and limited to 2,000 characters, while `thread_id` is
required, limited to 100 characters, and shape-validated. A pipeline failure
cannot change the already-committed HTTP 200, so it is reported in an SSE
`error` frame with the relevant `PipelineError.status`. SSE events are
`progress`, `token`, `result`, and `error`. Markdown output is sanitized in
the browser before insertion.

The frontend stores its sticky `thread_id` in `localStorage`, reuses it after
reload, and the **New chat** button mints and stores a fresh id. It sends the
current id on every request. The frontend does not label whether an answer
came from the sourced expert or the uncited chat branch.

## Compose, environment, and commands

The base Compose file defines Postgres, backend, frontend, and Phoenix.
Postgres has a `pg_isready` healthcheck; the backend depends on Postgres with
`condition: service_healthy` and on Phoenix with `condition: service_started`.
Development ports are frontend 8082, backend 3001, PostgreSQL 55432, and
Phoenix 6006 (Phoenix is loopback-bound by the dev override). Production adds
health checks, restart policies, TLS mounting, and nginx Basic Auth covering
both `/` and `/api/`. Production sets `AUTH_REQUIRED=true`, which fails closed
if either credential is missing; local development uses an unauthenticated
nginx configuration.

Run Python commands from `app/`: `uv sync --locked --dev`, `make test`,
`make integration_tests`, `make lint`, and `make format`. Use `langgraph dev`
from `app/` to drive either the `expert` or `orchestrator` graph in Studio.
CI runs `uv sync --locked --dev` from `app/` on Python 3.11 and does not use
the root requirements file; Compose builds `./app` and `./frontend`.
From the repository root, use the generic `make logs-SERVICE` target to follow
any Compose service, such as `frontend`, `backend`, `postgres`, or `phoenix`,
and use `make services` to list all services in the effective Compose
configuration.

The old `app/evals/` pilot is gone. Manual quality evaluation consists of
`app/tests/manual_quality/basic_agent_evaluation.py` and `cases.json`. The
script records one live expert experiment and one overlapping
full-orchestrator experiment in Phoenix. It does not render scores or judge
explanations itself: follow the Phoenix client experiment links and review
each experiment's native Evaluations view, which contains the score, label,
explanation, task output, and linked traces. The terminal retains only
Phoenix SDK progress/summary output and CLI diagnostics. It is not collected by
pytest, run in CI, or copied into runtime images. Live dependency or judge
failures are invalid and unscored; results are advisory. Phoenix retains
unredacted prompts, fetched article text, answers, and judge data. Run it with:

```bash
docker compose up -d phoenix
cd app
PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006/v1/traces \
  uv run python tests/manual_quality/basic_agent_evaluation.py
```

The root `.env` supplies `OPENAI_API_KEY` and `BRAVE_SEARCH_KEY` for this run;
`DATABASE_URL` is not required because the manual orchestrator graph has no
checkpointer.

There is exactly one `.env`, at the repo root. `config.py` resolves it by
absolute path, `app/langgraph.json` uses `env: "../.env"`, and Compose's
`env_file: .env` reads the same file. There is no separate `app/.env`.
`OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`, and `DATABASE_URL` are required for the
API. Compose derives `DATABASE_URL` from `POSTGRES_PASSWORD`; a bare API start
without it refuses to start. Model, timeout, token, CORS, and rate-limit knobs
remain hardcoded in code. `PHOENIX_COLLECTOR_ENDPOINT` and
`PHOENIX_PROJECT_NAME` are optional tracing switches; unset means no tracing,
and exported spans carry full prompt/response text with no redaction.

## Change Guidance

- Keep state flat where applicable and have nodes return partial dictionaries without mutation.
- Put sequencing in graph edges; do not reintroduce removed pipeline concepts.
- Preserve the shared-to-agent import direction and policy parameterization.
- Add focused tests under `app/tests/` and keep explicit module imports where package `__init__` files re-export functions.
- Do not modify `.env` files, commit secrets, or add top-level Python modules.
