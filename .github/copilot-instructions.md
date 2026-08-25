# Copilot Instructions

After any change in the codebase, update all three guidance files together:
`AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md`. Keep their
repository facts and rules consistent, especially after changes to the graph,
API, deployment, workflow, dependencies, or environment.

## Repository Map

The maintained application is under `app/`. Use `app/pyproject.toml` and
`app/uv.lock` for Python dependencies. The root `Dockerfile`, `main.py`, and
`requirements.txt` are stale legacy files; CI still references the root
requirements file, so do not treat it as the application source of truth.

- `app/src/` is the Python import root and uses bare imports.
- `app/src/nodes/` contains all LangGraph nodes.
- `app/tests/` contains unit and integration tests.
- `frontend/` is a static Alpine.js/`marked.js` frontend with no bundler.
- `ai_tools_tables.md` inventories repository skills and hooks by provider.
- `.github/skills/` contains Copilot skills; `.opencode/skills/` is their
  OpenCode-compatible mirror.

## Architecture

The graph in `app/src/graph.py` is:

```text
ingest_request -> build_research_plan
  -> four parallel search/analyst lanes
  -> referee
     -> blocked: referee_blocked_summary -> supervisor -> END
     -> continue: cross_check_facts -> compose_final -> supervisor -> END
```

`PipelineState` is defined in `app/src/models.py`. Accumulating lists use
LangGraph reducers. `ResearchPlan` and `RefereeReport` are dataclasses stored
in state. The graph is compiled once at import time and currently has no
checkpointer or persistent store.

English and Polish are separate infospheres. Their source allow-lists live in
`app/src/config.py`; do not mix source lists or prompt language. Request
configuration is passed through `RunnableConfig["configurable"]` by
`build_runtime_config()`. Preserve this pattern instead of adding partial
wrappers.

Search in `app/src/search.py` uses Brave Search, lane-specific `site:` filters,
domain validation, and lane-prefixed source IDs (`L`, `C`, `R`, `P`, `F`). LLM
calls belong in `app/src/llm.py`, using the existing structured/text wrappers
and `LLMInvocationError` boundary. Database logging is optional and must stay
a no-op when `DATABASE_URL` is absent.

## API and Runtime

`app/src/api.py` provides `/api/health`, synchronous `/api/run_pipeline`, and
SSE `/api/run_pipeline/stream`. The request fields are `query` and
`infosphere`; queries are normalized and limited to 2,000 characters. The API
also applies in-process IP-based rate limiting and configurable CORS.

From the repository root, use `make up`, `make down`, `make logs`, and
`make config`. Default development ports are frontend `8082`, backend `3001`,
and PostgreSQL `55432`. From `app/`, use `uv sync --locked --dev`, `make test`,
`make lint`, and `make format`. CI runs Python 3.11 with `uv run pytest`.

Required live-service variables are `OPENAI_API_KEY` and `BRAVE_SEARCH_KEY`.
Do not edit `.env` files or expose secrets.

## Change Rules

- Make the smallest change in the module that owns the behavior.
- Nodes return partial state dictionaries and should not mutate shared state.
- Keep routing in graph edges; update referee routing when its branches change.
- Add focused tests under `app/tests/` for behavior changes.
- Do not add top-level Python modules.
- After any codebase change, update `AGENTS.md`, `CLAUDE.md`, and
  `.github/copilot-instructions.md` together so all supported agents have
  current instructions.
