# CLAUDE.md

Guidance for Claude Code working in this repository. After any codebase change,
update `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` together.

The maintained application is under `app/`; the root Dockerfile and
requirements-export file are compatibility files (the old root `main.py` CLI
shim is gone). Shared modules in `app/src/` provide environment/model config,
shared models/errors, policy-parameterized Brave and trafilatura search, the
OpenAI boundary, API delivery, and optional tracing. Shared modules never
import an agent. There is no `prompt_logs` persistence path or `database.py`;
Postgres is used only by the LangGraph checkpointer. The app declares the
`psycopg[binary]` dependency directly, so it does not require a system
`libpq` installation.

Repository-local Codex skills live under `.codex/skills/`. Explicit
`$plan-from-brainstorm`, `$improve-plan`, and `$implement-plan` skills are the
Codex equivalents of the three Claude planning commands; they use this
repository's `explorer`, `critic`, and `builder` roles rather than
Claude-specific agent types. `.codex/skills/grill-me` provides a
one-question-at-a-time adversarial design-review workflow and persists its
session artifact under `docs/brainstorming/`.
The repository-local Codex `critic` agent is read-only and uses
`gpt-5.6-terra` with high reasoning effort.
The Codex catalog contains the full 16-skill `python-*` suite from
`.claude/skills/`, in addition to the Python quickstarts already shared by the
framework skill sets. Its `phoenix-cli`, `phoenix-evals`, and `phoenix-tracing`
packages are concrete project-local copies converted to Codex-valid
frontmatter, not symlinks.
The project-local `docs-manage`, `docs-search`, and `fetch-url` skills manage
and query the Grounded Docs index or fetch a single page; they require Node.js
22 or newer and `npx`.
The canonical Phoenix sources remain under `.agents/skills/`; OpenCode loads
them through the `skills.paths` entry in `opencode.jsonc`, while Claude exposes
them through symlinks in `.claude/skills/`.
No external documentation MCP server is configured in the repository.

Agent-specific code is under `app/src/agents/<name>/`. Each agent keeps its
prompts in `prompts.py`, one constant per node or purpose, and its static data
in `consts/`. Config is hardcoded dataclasses, not env-parsed getters; per-node
settings are passed explicitly into calls.

The API runs this orchestrator:

```text
START -> classify -> expert -> END
                  \-> chat   -> END
```

Geopolitical turns invoke the compiled expert inside the `expert` node; other
turns use the orchestrator's own uncited chat branch. Do not pass the expert
compiled graph directly to `add_node`: its `{query, sources, answer}` state
shares no key with the orchestrator, and LangGraph can silently discard the
child result. The expert remains separately available in Studio and is:

```text
START -> search_and_fetch -> answer -> END
```

The expert performs three Brave batches, extracts allow-listed pages with
trafilatura, and sends only fetched article text to one streamed plain-text
model call. Its search, source, and model failures are hard errors with no
degraded fallback.

The API accepts exactly `{query, thread_id}`. The query is normalized and capped
at 2,000 characters; `thread_id` is required, shape-validated, and identifies
the persistent conversation. API startup requires `DATABASE_URL`, opens a
Postgres connection pool, runs `AsyncPostgresSaver.setup()`, and compiles the
orchestrator with that checkpointer. `build_graph()` itself remains usable
without a checkpointer for tests and `langgraph dev`.

`api.py` drives the graph with
`stream_mode=["updates", "messages"]` and `subgraphs=True`, handling
`(namespace, mode, data)` events. It forwards route updates and only answer
messages from nodes `answer` and `chat`, narrowed to `AIMessage` and flattened
with `BaseMessage.text()`. Progress is Thinking, branch-specific Searching,
then Writing. Pipeline failures arrive inside SSE `error` frames rather than
changing the committed HTTP status; known pipeline failure statuses are 422,
503, and 502, with 500 as the generic fallback. The frontend sanitizes rendered
Markdown,
keeps its thread id in `localStorage`, sends it on every request, and offers a
**New chat** button that creates a fresh id.

`_generate` caps emitted output at 50,000 characters but drains an over-limit
upstream stream before emitting the capped result so checkpoint writes can
complete.

The base Compose file has a Postgres `pg_isready` healthcheck. The backend
depends on Postgres being healthy and Phoenix being started. Development ports
are frontend 8082, backend 3001, PostgreSQL 55432, and Phoenix 6006 via the
loopback-bound dev override; the base service keeps Phoenix internal and its
data in a `phoenix_data` volume. Production adds health checks, restart
policies, TLS mounting, and nginx Basic Auth covering both `/` and `/api/`.
With `AUTH_REQUIRED=true`, missing credentials fail closed; local development
remains unauthenticated.

From `app/`, use `uv sync --locked --dev`, `make test`,
`make integration_tests`, `make lint`, `make format`, and `langgraph dev`.
CI uses the app lockfile and does not reference root requirements; Compose
builds `./app` and `./frontend`.
From the repository root, the generic `make logs-SERVICE` target follows any
Compose service, such as `frontend`, `backend`, `postgres`, or `phoenix`, while
`make services` lists all services in the effective Compose configuration.

The old `app/evals/` pilot is gone. Manual quality evaluation consists of
`app/tests/manual_quality/basic_agent_evaluation.py` and `cases.json`. The
script records one live expert experiment and one overlapping
full-orchestrator experiment in Phoenix, including each LLM judge's
classification and explanation. It is not collected by pytest, run in CI, or
copied into runtime images. Live dependency or judge failures are invalid and
unscored; results are advisory. Phoenix retains unredacted prompts, fetched
article text, answers, and judge data. Run it with:

A follow-up implementation plan to move reviewer-facing result presentation
from the script's custom console summary to Phoenix's native experiment
Evaluations view is in
`docs/superpowers/plans/2026-09-02-phoenix-native-evals-ui.md`.

```bash
docker compose up -d phoenix
cd app
PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006/v1/traces \
  uv run python tests/manual_quality/basic_agent_evaluation.py
```

The root `.env` supplies `OPENAI_API_KEY` and `BRAVE_SEARCH_KEY` for this run;
`DATABASE_URL` is not required because the manual orchestrator graph has no
checkpointer.

There is exactly one `.env` at the repo root. `config.py` resolves it by
absolute path, `app/langgraph.json` points to `../.env`, and Compose's
`env_file: .env` reads it. There is no separate `app/.env`.
`OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`, and `DATABASE_URL` are required by the
API; Compose derives the database URL from `POSTGRES_PASSWORD`. Phoenix
tracing is optional and controlled by `PHOENIX_COLLECTOR_ENDPOINT` and
`PHOENIX_PROJECT_NAME`; tracing never raises and exported spans contain full
prompt/response text without redaction. CORS origins and rate limits are
hardcoded in `api.py`, not read from the environment.

Keep changes local, return partial state updates, preserve import direction,
add focused tests, avoid `.env` and secrets, and update all three guidance
files for every codebase change.
