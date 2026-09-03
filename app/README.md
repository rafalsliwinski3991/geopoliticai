# GeopoliticAI

This application puts an orchestrator in front of the two-node expert agent.
The orchestrator routes geopolitical turns to a nested expert and other turns
to its own conversational branch:

```text
START -> classify -> expert -> END
                  \-> chat   -> END
```

The expert remains independently available in LangGraph Studio. Its graph is:

```text
START -> search_and_fetch -> answer -> END
```

`search_and_fetch` runs three batched Brave queries, fetches up to ten
allow-listed pages, and extracts article text with trafilatura. `answer` sends
the retrieved text to one streamed OpenAI plain-text call. Search, extraction,
and model failures are surfaced to clients; the expert has no degraded answer.

Agent-specific code lives under `src/agents/`; shared retrieval and LLM
boundaries are in `src/search.py` and `src/llm.py`. The API accepts
`{query, thread_id}` and persists conversation state in a required Postgres
checkpointer. The static frontend is English-only, keeps its thread id in
`localStorage`, and provides a **New chat** button.

With Compose, Postgres has a `pg_isready` healthcheck and the backend waits for
the database to become healthy. `DATABASE_URL` is required by the API;
Compose derives it from `POSTGRES_PASSWORD`.
The checkpointer uses the direct `psycopg[binary]` dependency, which does not
require a system `libpq` installation. There is no `prompt_logs` persistence
path or `src/database.py`; Postgres is used only for LangGraph checkpoints.

The streaming endpoint caps emitted answers at 50,000 characters while
`_generate` drains the upstream stream after reaching the cap, before emitting
the result, so checkpoint writes can complete. Production nginx applies Basic
Auth to both `/` and `/api/`; `AUTH_REQUIRED=true` fails closed without
credentials, while local development remains unauthenticated.

## Getting started

```bash
uv sync --locked --dev
cp ../.env.example ../.env  # populate at the repo root, not under app/
langgraph dev
```

There is a single canonical `.env` at the repo root; `config.py` resolves it
by absolute path regardless of working directory, `langgraph.json`'s `env`
field points at `../.env`, and Docker Compose's `env_file: .env` reads the
same file. There is no separate `app/.env`. Required environment variables
for the API are `OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`, and `DATABASE_URL`.
Compose supplies `DATABASE_URL` from `POSTGRES_PASSWORD`; the API refuses to
start without it. Never commit the populated file. Optional settings are
documented in the repository guidance files.

Run checks with `make lint`, `make test`, and `make integration_tests`.
