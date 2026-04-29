# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Keep this file in sync with the codebase.** After any significant change (e.g., new agent nodes, API route changes, env var additions, architecture shifts), update the relevant section here so future Claude instances have accurate context.

## Project layout

The live code lives under `app/`. The repository root also contains a stale `Dockerfile`, `main.py`, and `requirements.txt` that import a no-longer-existing `geopoliticai` package — **do not use them**, they only persist because the GitHub Actions workflow (`.github/workflows/unit-tests.yml`) still references `requirements.txt`. The shipped image is built from `app/Dockerfile`, and the CLI/API entrypoints are in `app/src/`.

- `app/src/` — Python package; treated as the import root (`PYTHONPATH=/app/src` in containers). Modules use bare `from agents import ...`, `from models import ...` style, so the package directory must be on `sys.path`.
- `frontend/` — single `index.html` (Alpine.js + `marked.js` from CDN) plus `assets/`. No bundler. Served either directly by FastAPI (dev) or by nginx (prod).
- `docker-compose.yml` + `docker-compose.override.yml` — local dev. The override mounts `app/src` and `frontend/` into the backend container, exposes port `3000:8000`, and runs uvicorn with `--reload`. The frontend container is gated behind the `production` profile, so `docker compose up` runs only postgres + backend.
- `docker-compose.prod.yml` — adds restart policies, the `/api/health` healthcheck, TLS cert mount (`/etc/letsencrypt`), and basic-auth env vars; activates the frontend service.
- `app/langgraph.json` — registers `src/graph.py:graph` for LangGraph Studio (`langgraph dev`).

## Architecture

A multi-agent political analysis pipeline built on **LangGraph** (`StateGraph` over a `PipelineState` TypedDict) and **FastAPI**. The single source of truth for the flow is `app/src/graph.py`.

Pipeline shape (fan-out → converge → fact-check → compose):

```
ingest_request → build_research_plan → ┬─ search_left_pool   → left_analyst    ─┐
                                       ├─ search_center_pool → center_analyst  ─┤
                                       ├─ search_right_pool  → right_analyst   ─┼→ referee ──(blocked)──→ referee_blocked_summary → supervisor → END
                                       └─ search_people_pool → people_analyst  ─┘                │
                                                                                                 └──(continue)──→ extract_claims → cross_check_facts → compose_final → supervisor → END
```

- **Lanes** (`left`, `centrist`, `right`, `people`, plus `fact` for cross-checking): each lane has a curated source allow-list per infosphere defined in `app/src/config.py` (`ENGLISH_INFOSPHERE_SOURCES`, `POLISH_INFOSPHERE_SOURCES`). Search queries are constrained with `site:` filters built from those domains.
- **Infosphere** (`"english"` | `"polish"`): selected explicitly via the `--infosphere` CLI flag or the `infosphere` field in API requests. CLI auto-detects via `detect_language()` in `models.py` (Polish diacritics + stopword tokens). The infosphere drives both source pools and prompt language.
- **Referee** can short-circuit the pipeline (returns `blocked: true`), routing through `referee_blocked_summary` instead of fact-checking.
- **`compose_final`** writes the user-facing report; **`supervisor`** is the terminal node that emits `final_output`.
- **OpenAI calls** go through `app/src/llm.py`, which wraps both the Responses API and Chat Completions with JSON-mode output and graceful retries for `max_completion_tokens`/`temperature` compatibility issues across model variants. All structured outputs use `StructuredOutputChain` (Pydantic schema → JSON object).
- **Search** (`app/src/search.py`) calls Brave Search, restricted to lane-allowed domains; results are renumbered with lane-prefixed source IDs (`L1`, `C1`, `R1`, `P1`, `F1`).
- **Persistence**: `app/src/database.py` is an optional asyncpg pool that logs prompts and outputs into a `prompt_logs` table. Activated only when `DATABASE_URL` is set; otherwise log calls become no-ops. The pool is initialised in the FastAPI `lifespan` hook.
- **API**: `app/src/api.py` exposes `POST /api/run_pipeline` (sync) and `POST /api/run_pipeline/stream` (SSE with per-node progress events). Both enforce an in-process token-bucket rate limit keyed by `X-Forwarded-For` (or `request.client.host`). The streaming endpoint uses `graph.astream_events(version="v2")` and emits Polish or English progress labels based on the request's `infosphere`.
- **Frontend integration**: in dev, FastAPI mounts `/assets` and serves `frontend/index.html` at `/` via `FileResponse` (paths controlled by `FRONTEND_HTML_PATH`). In prod, nginx serves the static frontend and proxies `/api/` to the backend. `frontend/nginx.conf` is the prod config (TLS + basic auth via `docker-entrypoint.sh` writing `htpasswd`); `frontend/nginx.local.conf` exists but is not currently wired into any compose file.

## Common commands

All Python commands assume `cd app/` first.

```bash
# Install (uses uv; the Dockerfile pins via uv.lock)
uv sync                                 # full install incl. dev deps
pip install -e . "langgraph-cli[inmem]" # alt for ad-hoc langgraph dev

# Run the API locally (with auto-reload via override compose)
docker compose up                       # postgres + backend on http://localhost:3000
# Backend hot-reloads on edits to app/src/

# Run the production stack (frontend + backend + postgres)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# LangGraph Studio (uses app/langgraph.json)
langgraph dev

# CLI invocation
python src/cli.py "your query" --infosphere polish --report full
python src/cli.py "your query" --report compact --log-level DEBUG

# Tests
make test                               # unit tests (tests/unit_tests/)
make test TEST_FILE=tests/unit_tests/test_api.py
python -m pytest tests/unit_tests/test_api.py::test_name -vv  # single test
make integration_tests                  # tests/integration_tests/ — hits real APIs

# Lint / format (ruff + mypy --strict)
make lint                               # check only
make format                             # apply fixes
make spell_check                        # codespell
```

## Required environment

Set in `.env` at the repo root (loaded by docker compose) or `app/.env` (loaded via `python-dotenv` in `init_environment()`):

- `OPENAI_API_KEY`, `BRAVE_SEARCH_KEY` — required; `require_env()` raises on startup if missing.
- `DATABASE_URL` — optional; without it, prompt logging is silently disabled.
- `CORS_ALLOW_ORIGINS` — comma-separated; defaults to localhost variants.
- `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_OUTPUT_TOKENS`, `ANALYST_ADDITIONAL_SOURCES` — tuning knobs read by `config.py`.
- `API_RATE_LIMIT_REQUESTS`, `API_RATE_LIMIT_WINDOW_SECONDS` — rate-limit overrides.
- `AUTH_USER`, `AUTH_PASSWORD` — only consumed by the prod frontend container's entrypoint to generate `htpasswd` for nginx basic auth.
- `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` — optional tracing.
- `FRONTEND_HTML_PATH` — override only if the frontend bind mount path differs from `/app/frontend/index.html`.

## Things that bite

- **Don't add new top-level Python modules to the repo root.** Imports inside `app/src/` assume `src/` is on `sys.path` (set as `PYTHONPATH=/app/src` in the override compose; `tool.setuptools.package-dir` in `pyproject.toml`). Adding `geopoliticai/` at the root will not be picked up.
- **Polish vs English prompts and sources are not interchangeable.** Both the LLM prompts and the curated `INFOSPHERE_SOURCES` switch on the `language`/`infosphere` argument that's threaded through every node via `functools.partial` in `build_graph()`.
- **The graph is recompiled per request in the streaming endpoint** (`build_graph(infosphere=...)`) so that the per-language partials are correct. The synchronous endpoint goes through `run_pipeline()` which does the same.
- **`compose_final`** depends on referee not having blocked — if you change routing, also update the `_route_after_referee` conditional in `graph.py`.
- **CI uses the stale top-level `requirements.txt`**, not `app/pyproject.toml`. If you change runtime deps in `pyproject.toml`, the CI workflow won't pick them up unless you also update `requirements.txt` (or fix the workflow).
