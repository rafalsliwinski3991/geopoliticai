# AGENTS.md

Guidance for coding agents working in this repository. After any change in the
codebase, update all three guidance files together: `AGENTS.md`, `CLAUDE.md`,
and `.github/copilot-instructions.md`. Keep their repository facts and rules
consistent, especially after changes to the graph, API, deployment, workflow,
dependencies, or environment.

## Repository Layout

The application lives under `app/`. The root-level `Dockerfile`, `main.py`,
and `requirements.txt` are stale and import a removed package. Do not use them
for local development. The CI workflow still references the root
`requirements.txt`, so update the workflow if that legacy dependency path is
ever removed.

- `app/src/` - Python import root and application modules. Imports inside this
  directory are intentionally bare (`from nodes import ...`).
- `app/src/nodes/` - LangGraph node implementations for ingestion, planning,
  search pools, analyst lanes, referee checks, fact checking, composition,
  and final supervision.
- `app/tests/` - unit and integration tests.
- `frontend/` - static Alpine.js and `marked.js` client, with assets; there is
  no frontend bundler.
- `app/langgraph.json` - LangGraph CLI registration for `src/graph.py:graph`.
- `docker-compose*.yml` - development and production service definitions.

## Architecture

The main workflow is defined in `app/src/graph.py`:

```text
START -> ingest_request -> build_research_plan
  -> search_left_pool   -> left_analyst
  -> search_center_pool -> center_analyst
  -> search_right_pool  -> right_analyst
  -> search_people_pool -> people_analyst
  -> referee
     -> blocked: referee_blocked_summary -> supervisor -> END
     -> continue: cross_check_facts -> compose_final -> supervisor -> END
```

The four search/analysis lanes fan out from the research plan and converge at
the referee. `PipelineState` is a `TypedDict` in `app/src/models.py`; its
accumulating source, fact-check, and error fields use `Annotated` with
`operator.add`. `ResearchPlan` and `RefereeReport` are dataclasses stored
directly in state.

- Infospheres are `english` and `polish`. Sources are selected from the
  corresponding allow-list in `app/src/config.py`.
- CLI language detection is heuristic: Polish diacritics or known Polish
  stopwords select `polish`; otherwise it selects `english`.
- Per-request `infosphere`, `language`, and `report_mode` values are passed
  through `RunnableConfig["configurable"]` using `build_runtime_config()`.
  Do not reintroduce `functools.partial` wrappers for request-specific data.
- `app/src/search.py` queries Brave Search with lane-specific `site:` filters,
  rejects out-of-domain URLs, and assigns `L1`, `C1`, `R1`, `P1`, or `F1`
  source IDs.
- OpenAI calls are centralized in `app/src/llm.py`. Structured calls use
  `StructuredOutputChain`; final composition uses `TextOutputChain` and
  `LLMInvocationError` is the provider-failure boundary.
- `app/src/database.py` optionally logs prompts and outputs to PostgreSQL when
  `DATABASE_URL` is set. Without it, logging is a no-op. The pool is managed
  by the FastAPI lifespan.
- The graph is compiled once at module import. It currently has no
  checkpointer or long-term store; `thread_id` is accepted in runtime config
  for request context but does not provide persistence by itself.

## API and Frontend

`app/src/api.py` exposes:

- `GET /api/health`
- `POST /api/run_pipeline` returning `{ "output": "..." }`
- `POST /api/run_pipeline/stream` returning SSE progress and output events
- `GET /` serving `frontend/index.html` when available

The request body contains `query` and `infosphere` (`english` or `polish`).
The query is whitespace-normalized and limited to 2,000 characters. API calls
are rate-limited in process by forwarded client IP or socket client address.
CORS origins come from `CORS_ALLOW_ORIGINS` or localhost defaults.

In development, the compose override mounts source code and frontend assets
and runs uvicorn with reload. Default ports from the root `Makefile` are:

- frontend: `8082`
- backend: `3001`
- PostgreSQL: `55432`

The production compose file adds backend health checks, restart policies,
TLS certificate mounting, and nginx basic authentication. The frontend
container proxies `/api/` to the healthy backend.

## Development Commands

Run Python commands from `app/`:

```bash
uv sync --locked --dev
make test                         # unit tests
make test TEST_FILE=tests/unit_tests/test_api.py
make integration_tests            # live integration tests
make lint                         # ruff and strict mypy
make format
```

From the repository root:

```bash
make up                          # build and start the compose stack
make down
make logs
make config
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

LangGraph Studio uses `app/langgraph.json`:

```bash
cd app
langgraph dev
```

CLI examples:

```bash
cd app
python src/cli.py "your query" --infosphere polish --report full
python src/cli.py "your query" --report compact --log-level DEBUG
```

CI installs `app/pyproject.toml` with `uv sync --locked --dev` and runs
`uv run pytest` on Python 3.11. Required live-service variables are
`OPENAI_API_KEY` and `BRAVE_SEARCH_KEY`. Optional settings include
`DATABASE_URL`, `CORS_ALLOW_ORIGINS`, `OPENAI_TIMEOUT_SECONDS`,
`OPENAI_MAX_OUTPUT_TOKENS`, `ANALYST_ADDITIONAL_SOURCES`,
`API_RATE_LIMIT_REQUESTS`, `API_RATE_LIMIT_WINDOW_SECONDS`, `LOG_LEVEL`, and
`FRONTEND_HTML_PATH`. LangSmith variables are optional tracing settings.

## Change Guidance

- After any codebase change, update `AGENTS.md`, `CLAUDE.md`, and
  `.github/copilot-instructions.md` together so all supported agents have
  current instructions.
- Keep state flat and return partial state dictionaries from nodes; do not
  mutate shared state in place.
- Put routing in graph edges, especially changes to referee blocked/continue
  behavior.
- Preserve the distinction between Polish and English prompts and source
  lists.
- Add or update focused tests in `app/tests/` for behavior changes.
- Do not modify `.env` files or commit secrets.
- Do not add top-level Python modules; application imports assume `app/src/`
  is on `sys.path`.
