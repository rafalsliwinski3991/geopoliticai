# geopoliticai

An English-language geopolitical research assistant built on LangGraph.

## What it is

The API runs an orchestrator that routes each turn to one of three branches:

```text
START -> classify -> expert -> END
                  \-> chat   -> END
                  \-> reporter -> END
```

Geopolitical turns are delegated to the nested expert. Other turns are answered
by the orchestrator's own general-assistant branch, without source citations.
Report requests pause at an outline the user approves, revises, or cancels by
typing a reply; the static frontend distinguishes the finished report, giving
it Download .md and Copy actions.

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
checkpointer. The API request body is exactly one of `{query, thread_id}` or
`{resume, thread_id}`, where the resume carries the reply to a paused outline;
both fields are normalized and capped at 2,000 characters. The frontend keeps
the thread id in `localStorage` across reloads and its **New chat** control
mints a new thread.

The API requires `OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`, `DATABASE_URL`, and `JWT_SIGNING_KEY`.
Compose derives `DATABASE_URL` from `POSTGRES_PASSWORD`, gives Postgres a
`pg_isready` healthcheck, and starts the backend only after Postgres is healthy.
The app declares `psycopg[binary]` directly for the checkpointer; no system
`libpq` installation is required. There is no `prompt_logs` persistence path or
`database.py` module: Postgres is used for LangGraph checkpoints only.

The stream caps emitted answers at 50,000 characters, but `_generate` continues
draining an over-limit upstream stream before emitting the capped result so the
checkpoint can complete. Production nginx applies Basic Auth to `/admin/` only; the
API is guarded by bearer JWTs verified by `auth.py`; `AUTH_REQUIRED=true` fails closed when credentials are missing, while
the local development configuration remains unauthenticated.

The maintained application lives under `agentic_backend/`. `agentic_backend/README.md` documents setup,
the API contract, and the static English frontend; `agentic_backend/src/` is the Python
import root. The FastAPI app exposes `GET /api/health`,
`POST /api/run_pipeline/stream`, and `/` for the frontend, with no synchronous
pipeline route. The streaming endpoint emits SSE `progress`, `token`, `pause`,
`result`, and `error` events, with `result` carrying `kind` and `truncated`;
a paused turn ends with `pause` and no `result` until the user's reply
resumes it.

A second service, `web_backend/`, hosts the Django identity service: accounts
(allauth, email-only with mandatory verification), the admin, and the
application tables. Its dev port is `ACCOUNTS_PORT` (default 8083). From the
host, `make migrate` runs its migrations (always before starting
`agentic-backend`, which runs the checkpointer's own schema setup at startup),
`make createsuperuser` creates an admin user, and `make test-web-backend` runs
its suite against the dev Postgres. The two services share the database and the
root `.env` but never each other's code.

## Deploy order (two migration systems share one database)

Django's `migrate` and the checkpointer's `setup()` touch disjoint tables, but
the checkpointer uses `CREATE INDEX CONCURRENTLY`, which cannot run inside a
transaction — so the order is explicit and not incidental:

1. `docker compose run --rm web-backend python manage.py migrate`, then
   `docker compose run --rm web-backend python manage.py createcachetable` —
   the `DatabaseCache` table allauth's rate limiter reads on the first login
   (the root `make migrate` target runs both)
2. start `agentic-backend` (its lifespan runs `checkpointer.setup()`)
3. start `frontend`

Do not add a migrate-on-start hook to the `web-backend` container: two
replicas would race. Before the Basic Auth cutover (`users-auth/07`), run the
pre-launch purge with a `pg_dump` in hand: `purge_prelaunch_threads --dry-run`,
read the count, then `--apply` — deleted checkpointer rows are recoverable only
from that dump.

**Operator-side spend caps (not code, and not optional):** configure hard
spend caps in the OpenAI and Brave dashboards before going live — they are the
only control that still holds when the application-layer quota
(`DAILY_RESEARCH_TURNS` and its site-wide ceiling) is wrong. Record the
configured figures here next to the deploy order.

The chat SPA's build stage (`npm ci`) reaches a registry at deploy time, which
today's `COPY index.html` build never did. A registry outage, a yanked
transitive dependency or a Node EOL bump breaks only that stage — the
mitigation is not in the Dockerfile: **the previous image stays in the
registry, and a rollback is a tag change to the last good frontend tag.**
