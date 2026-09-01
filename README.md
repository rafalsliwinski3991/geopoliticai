# geopoliticai

An English-language geopolitical research assistant built on LangGraph.

## What it is

The API runs an orchestrator that routes each turn to one of two branches:

```text
START -> classify -> expert -> END
                  \-> chat   -> END
```

Geopolitical turns are delegated to the nested expert. Other turns are answered
by the orchestrator's own general-assistant branch, without source citations.
The static frontend does not distinguish the two answer paths.

The expert remains separately available in LangGraph Studio and is a two-node
graph:

```text
START -> search_and_fetch -> answer -> END
```

`search_and_fetch` runs three batched Brave queries restricted to a curated set
of domains, fetches up to ten of those pages, and extracts article text with
trafilatura. `answer` sends the retrieved text to one streamed plain-text OpenAI
call. Search, extraction, and model failures are surfaced to the client; the
expert has no degraded or fabricated fallback.

Conversation threads are persisted by a required Postgres LangGraph
checkpointer. The API request body is `{query, thread_id}`. The frontend keeps
the thread id in `localStorage` across reloads and its **New chat** control
mints a new thread.

The API requires `OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`, and `DATABASE_URL`.
Compose derives `DATABASE_URL` from `POSTGRES_PASSWORD`, gives Postgres a
`pg_isready` healthcheck, and starts the backend only after Postgres is healthy.
The app declares `psycopg[binary]` directly for the checkpointer; no system
`libpq` installation is required. There is no `prompt_logs` persistence path or
`database.py` module: Postgres is used for LangGraph checkpoints only.

The stream caps emitted answers at 50,000 characters, but `_generate` continues
draining an over-limit upstream stream before emitting the capped result so the
checkpoint can complete. Production nginx applies Basic Auth to both `/` and
`/api/`; `AUTH_REQUIRED=true` fails closed when credentials are missing, while
the local development configuration remains unauthenticated.

The maintained application lives under `app/`. `app/README.md` documents setup,
the API contract, and the static English frontend; `app/src/` is the Python
import root. The FastAPI app exposes `GET /api/health`,
`POST /api/run_pipeline/stream`, and `/` for the frontend, with no synchronous
pipeline route. The streaming endpoint emits SSE `progress`, `token`, `result`,
and `error` events.
