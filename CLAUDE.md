# CLAUDE.md

Guidance for Claude Code working in this repository. After any codebase change,
update `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` together.

The maintained application is under `app/`; root files are compatibility
entrypoint, Docker, and requirements-export files. Shared modules in
`app/src/` provide environment/model config, shared models/errors, a
policy-parameterized Brave and trafilatura search boundary, the OpenAI boundary,
and API/CLI/database delivery. Agent-specific code is under
`app/src/agents/<name>/`; shared modules never import an agent.

The expert graph is `START -> search_and_fetch -> answer -> END`. Its state has
exactly `query`, `sources`, and `answer`, without reducers. The expert policy is
an English allow-list passed as `SourcePolicy`; search performs exactly three
Brave batches and only extracted allow-listed page text reaches one streamed
plain-text model call. Failures are hard errors with no degraded fallback.

The API accepts only `{query}` (normalized, max 2,000 characters), serves sync
and SSE endpoints, and maps no sources/search outage/LLM failures to 422/503/502.
The English frontend sanitizes rendered Markdown. LangGraph configuration names
the graph `expert`.

From `app/`, use `uv sync --locked --dev`, `make test`, `make integration_tests`,
`make lint`, `make format`, and `langgraph dev`; the CLI is
`python src/cli.py "your query"`. CI uses the app lockfile and does not reference
root requirements; compose builds `./app` and `./frontend`.

There is exactly one `.env`, at the repo root. `config.py` resolves it by
absolute path regardless of working directory, `app/langgraph.json`'s `env`
field points at `../.env`, and Compose's `env_file: .env` reads the same
file; there is no separate `app/.env`. Compose wires `DATABASE_URL` from
`POSTGRES_PASSWORD` automatically, so prompt-log DB writes are on by
default whenever Postgres runs alongside the backend.

Keep changes local, return partial state updates, preserve import direction, add
focused tests, avoid `.env` and secrets, and update all three guidance files for
every codebase change.
