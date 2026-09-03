# Copilot Instructions

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

Shared modules under `app/src/` provide environment/model config, shared models
and errors, policy-parameterized Brave/fetch/extraction, OpenAI access, API
delivery, and an optional tracing boundary. There is no `database.py` or
`prompt_logs` persistence path; Postgres is used only for the LangGraph
checkpointer. The app declares `psycopg[binary]` directly, so no system `libpq`
installation is required. Agent packages under
`app/src/agents/<name>/` contain graph, state, hardcoded config, prompts, static
`consts/`, and node modules. Shared modules never import agents; the API names
`agents.orchestrator`, whose expert node invokes `agents.expert`.

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
From the repository root, the generic `make logs-SERVICE` target follows any
Compose service, such as `frontend`, `backend`, `postgres`, or `phoenix`, and
`make services` lists all services in the effective Compose configuration.
Nodes return partial state dictionaries without mutation, tests should use
explicit module imports when package initializers re-export functions, and no
`.env` or secrets should be changed.

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

There is exactly one `.env` at the repo root, read by the API, tests,
`langgraph dev` (`app/langgraph.json`'s `env: "../.env"`), and Compose's
`env_file: .env`; `config.py` resolves it by absolute path. There is no
separate `app/.env`. `OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`, and `DATABASE_URL`
are required by the API; Compose derives the database URL from
`POSTGRES_PASSWORD`. Phoenix tracing is optional, env-gated, idempotent, and
never raises; exported spans contain full prompt/response text without
redaction. CORS origins and rate limits are hardcoded in `api.py`.
