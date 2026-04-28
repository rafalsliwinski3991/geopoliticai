# AGENTS.md

This file provides guidance to Codex and other coding agents when working with code in this repository.

> **Keep this file in sync with the codebase.** After any significant change, such as new agent nodes, API route changes, env var additions, or architecture shifts, update the relevant section here so future agents have accurate context.

## Project Layout

The live code lives under `app/`. The repository root also contains a stale `Dockerfile`, `main.py`, and `requirements.txt` that import a no-longer-existing `geopoliticai` package. Do not use them, except that the GitHub Actions workflow `.github/workflows/unit-tests.yml` still references `requirements.txt`. The shipped image is built from `app/Dockerfile`, and the CLI/API entrypoints are in `app/src/`.

- `app/src/` - Python package; treated as the import root (`PYTHONPATH=/app/src` in containers). Modules use bare imports such as `from nodes import ...`, `from models import ...`, so the package directory must be on `sys.path`.
- `app/src/nodes/` - all LangGraph node callables, including search nodes, analyst nodes, referee, claim extraction, fact-checking, final composition, and supervisor rendering. The old `app/src/agents/` and `app/src/tools/` packages were merged into this package.
- `frontend/` - single `index.html` using Alpine.js and `marked.js` from CDN, plus `assets/`. No bundler. Served either directly by FastAPI in dev or by nginx in prod.
- `docker-compose.yml` and `docker-compose.override.yml` - local dev. The override mounts `app/src` and `frontend/` into the backend container, exposes port `3000:8000`, and runs uvicorn with `--reload`. The frontend container is gated behind the `production` profile, so `docker compose up` runs only postgres and backend.
- `docker-compose.prod.yml` - adds restart policies, the `/api/health` healthcheck, TLS cert mount (`/etc/letsencrypt`), and basic-auth env vars; activates the frontend service.
- `app/langgraph.json` - registers `src/graph.py:graph` for LangGraph Studio (`langgraph dev`).

## Architecture

A multi-agent political analysis pipeline built on LangGraph (`StateGraph` over a `PipelineState` `TypedDict`) and FastAPI. The single source of truth for the flow is `app/src/graph.py`.

Pipeline shape:

```text
ingest_request -> build_research_plan
  -> search_left_pool   -> left_analyst
  -> search_center_pool -> center_analyst
  -> search_right_pool  -> right_analyst
  -> search_people_pool -> people_analyst
  -> referee
     -> blocked: referee_blocked_summary -> supervisor -> END
     -> continue: extract_claims -> cross_check_facts -> compose_final -> supervisor -> END
```

- **Lanes** (`left`, `centrist`, `right`, `people`, plus `fact` for cross-checking): each lane has a curated source allow-list per infosphere defined in `app/src/config.py` (`ENGLISH_INFOSPHERE_SOURCES`, `POLISH_INFOSPHERE_SOURCES`). Search queries are constrained with `site:` filters built from those domains.
- **Infosphere** (`"english"` or `"polish"`): selected explicitly via the `--infosphere` CLI flag or the `infosphere` field in API requests. CLI auto-detects via `detect_language()` in `models.py` using Polish diacritics and stopword tokens. The infosphere drives both source pools and prompt language.
- **Runtime config**: graph nodes read `infosphere_sources`, `language`, and `report_mode` from LangGraph `RunnableConfig["configurable"]` via `nodes/runtime_config.py`. `build_runtime_config()` in `graph.py` is shared by sync and streaming entrypoints. Do not reintroduce `functools.partial` wrappers for per-request node settings.
- **State shape**: `PipelineState` stores `ResearchPlan` and `RefereeReport` dataclass instances directly. Accumulating list fields such as source lists, fact checks, and extracted claims use LangGraph `Annotated[..., operator.add]` reducers. The unused verification/rewrite loop state was removed.
- **Referee** can short-circuit the pipeline by returning `blocked: true`, routing through `referee_blocked_summary` instead of fact-checking.
- **`compose_final`** writes the user-facing report; **`supervisor`** is the terminal node that emits `final_output`.
- **OpenAI calls** go through `app/src/llm.py`, a thin LangChain wrapper around `langchain-openai` `ChatOpenAI.with_structured_output()` with a targeted retry when structured JSON is truncated by the output-token limit. All structured outputs use `StructuredOutputChain` or `invoke_structured_chain()` with Pydantic schemas.
- **Search** (`app/src/search.py`) calls Brave Search, restricted to lane-allowed domains; results are renumbered with lane-prefixed source IDs (`L1`, `C1`, `R1`, `P1`, `F1`).
- **Persistence**: `app/src/database.py` is an optional asyncpg pool that logs prompts and outputs into a `prompt_logs` table. Activated only when `DATABASE_URL` is set; otherwise log calls become no-ops. The pool is initialized in the FastAPI `lifespan` hook.
- **API**: `app/src/api.py` exposes `POST /api/run_pipeline` (sync) and `POST /api/run_pipeline/stream` (SSE with per-node progress events). Both enforce an in-process token-bucket rate limit keyed by `X-Forwarded-For` or `request.client.host`. The streaming endpoint uses `graph.astream_events(version="v2")` and emits Polish or English progress labels based on the request's `infosphere`.
- **Frontend integration**: in dev, FastAPI mounts `/assets` and serves `frontend/index.html` at `/` via `FileResponse` (paths controlled by `FRONTEND_HTML_PATH`). In prod, nginx serves the static frontend and proxies `/api/` to the backend. `frontend/nginx.conf` is the prod config with TLS and basic auth via `docker-entrypoint.sh` writing `htpasswd`; `frontend/nginx.local.conf` exists but is not currently wired into any compose file.

## Common Commands

All Python commands assume `cd app/` first.

```bash
# Install (uses uv; the Dockerfile pins via uv.lock)
uv sync
pip install -e . "langgraph-cli[inmem]"  # alternative for ad-hoc langgraph dev

# Run the API locally (with auto-reload via override compose)
docker compose up
# Backend hot-reloads on edits to app/src/

# Run the production stack (frontend + backend + postgres)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# LangGraph Studio (uses app/langgraph.json)
langgraph dev

# CLI invocation
python src/cli.py "your query" --infosphere polish --report full
python src/cli.py "your query" --report compact --log-level DEBUG

# Tests
make test
make test TEST_FILE=tests/unit_tests/test_api.py
python -m pytest tests/unit_tests/test_api.py::test_name -vv
make integration_tests

# Lint / format (ruff + mypy --strict)
make lint
make format
make spell_check
```

## Required Environment

Set variables in `.env` at the repo root (loaded by docker compose) or `app/.env` (loaded via `python-dotenv` in `init_environment()`):

- `OPENAI_API_KEY`, `BRAVE_SEARCH_KEY` - required; `require_env()` raises on startup if missing.
- `DATABASE_URL` - optional; without it, prompt logging is silently disabled.
- `CORS_ALLOW_ORIGINS` - comma-separated; defaults to localhost variants.
- `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_OUTPUT_TOKENS`, `ANALYST_ADDITIONAL_SOURCES` - tuning knobs read by `config.py`.
- `API_RATE_LIMIT_REQUESTS`, `API_RATE_LIMIT_WINDOW_SECONDS` - rate-limit overrides.
- `AUTH_USER`, `AUTH_PASSWORD` - only consumed by the prod frontend container's entrypoint to generate `htpasswd` for nginx basic auth.
- `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` - optional tracing.
- `FRONTEND_HTML_PATH` - override only if the frontend bind mount path differs from `/app/frontend/index.html`.

## Agent Operating Notes

- Do not add new top-level Python modules to the repo root. Imports inside `app/src/` assume `src/` is on `sys.path`, set as `PYTHONPATH=/app/src` in the override compose and via `tool.setuptools.package-dir` in `pyproject.toml`. Adding `geopoliticai/` at the root will not be picked up.
- Polish and English prompts and sources are not interchangeable. Both the LLM prompts and curated `INFOSPHERE_SOURCES` switch on the `language` or `infosphere` value passed through LangGraph runtime config.
- The graph is recompiled per request in the streaming endpoint (`build_graph(infosphere=...)`) and both sync and streaming paths pass per-request values with `build_runtime_config()`.
- `compose_final` depends on the referee not having blocked. If you change routing, also update the `_route_after_referee` conditional in `graph.py`.
- CI uses the stale top-level `requirements.txt`, not `app/pyproject.toml`. If you change runtime dependencies in `pyproject.toml`, CI will not pick them up unless you also update `requirements.txt` or fix the workflow.
- Prefer `rg` for repository searches and keep edits scoped to the task. Do not modify `.env` files or secrets unless the user explicitly asks.
