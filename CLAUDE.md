# CLAUDE.md

Guidance for Claude Code working in this repository. After any change in the
codebase, update all three guidance files together: `AGENTS.md`, `CLAUDE.md`,
and `.github/copilot-instructions.md`. Keep their repository facts and rules
consistent, especially after changes to the graph, API, deployment, workflow,
dependencies, or environment.

## Project Layout

The live application is under `app/`; the root-level `Dockerfile`, `main.py`,
and `requirements.txt` are stale legacy files. Use `app/pyproject.toml` and
`app/uv.lock` for the maintained Python environment. CI still references the
root `requirements.txt`, so account for that legacy workflow before removing
it.

- `app/src/` - Python import root; modules use bare imports such as
  `from nodes import ...`.
- `app/src/nodes/` - all graph node implementations.
- `app/tests/` - unit and integration tests.
- `frontend/` - static Alpine.js/`marked.js` frontend and assets.
- `.github/skills/` - Copilot skills, references, scripts, and templates.
- `.opencode/skills/` - OpenCode-compatible mirror of those skills.
- `app/langgraph.json` - LangGraph CLI entrypoint configuration.

## Workflow

`app/src/graph.py` is the source of truth:

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

The four lanes run from the research plan and converge at `referee`. The
`PipelineState` `TypedDict` lives in `app/src/models.py`; `ResearchPlan` and
`RefereeReport` are dataclasses, while accumulating lists use LangGraph
reducers. Search is constrained by the English or Polish source allow-lists
in `app/src/config.py`. Brave results are checked against allowed domains and
renumbered with lane prefixes.

Nodes receive request-specific `infosphere_sources`, `language`, and
`report_mode` through `RunnableConfig["configurable"]`. Use
`build_runtime_config()` in `graph.py` for both sync and streaming calls.
The graph is compiled once and currently has no checkpointer or persistent
store; a supplied `thread_id` is configuration context only.

OpenAI access belongs in `app/src/llm.py`. Use the existing structured/text
chain wrappers and preserve the `LLMInvocationError` boundary. Optional prompt
logging belongs in `app/src/database.py` and must remain a no-op when
`DATABASE_URL` is unset.

## API and Deployment

`app/src/api.py` provides `GET /api/health`, synchronous and SSE streaming
`POST /api/run_pipeline` endpoints, and serves the static frontend at `/` in
development. Requests contain `query` and `infosphere`; queries are cleaned
and capped at 2,000 characters. The API applies an in-process rate limit and
CORS configuration from environment variables.

The root compose files define PostgreSQL, backend, and frontend services. The
development override mounts `app/src` and frontend files and runs uvicorn
reload. Root `Makefile` defaults are frontend `8082`, backend `3001`, and
PostgreSQL `55432`. Production adds nginx TLS/basic auth, backend health
checks, and restart policies.

## Commands

```bash
# From app/
uv sync --locked --dev
make test
make test TEST_FILE=tests/unit_tests/test_api.py
make integration_tests
make lint
make format

# From the repository root
make up
make down
make logs
make config

# LangGraph Studio
cd app && langgraph dev

# CLI
cd app && python src/cli.py "your query" --infosphere polish --report full
```

CI uses Python 3.11, `uv sync --locked --dev`, and `uv run pytest` from `app/`.
Required environment variables are `OPENAI_API_KEY` and `BRAVE_SEARCH_KEY`.
Optional variables include `DATABASE_URL`, `CORS_ALLOW_ORIGINS`, OpenAI
timeouts/token limits, analyst source counts, API rate limits, `LOG_LEVEL`,
`FRONTEND_HTML_PATH`, and LangSmith tracing settings.

## Working Rules

- After any codebase change, update `AGENTS.md`, `CLAUDE.md`, and
  `.github/copilot-instructions.md` together so all supported agents have
  current instructions.
- Keep changes local to the owning module and preserve public APIs.
- Return partial state updates from nodes; avoid in-place mutation.
- Keep routing in graph edges and update `_route_after_referee` if the referee
  branches change.
- Keep Polish and English prompts, sources, and progress labels distinct.
- Add focused tests under `app/tests/` for behavior changes.
- Never edit `.env` files or expose secrets.
- Do not add application modules at the repository root.
