# CLAUDE.md

Update this file only for changes to the application codebase. Changes to
AI-harness tooling (Claude commands, skills, agents, plugins, and similar
configuration) do not require updating it.

## Application

`agentic_backend/` is the maintained FastAPI application and `web_backend/` is the maintained
Django identity service. The root `Dockerfile` and `requirements.txt` are unused
compatibility files (re-export `requirements.txt` with the command in its header whenever
`agentic_backend/uv.lock` changes); the root `docker-compose*.yml` files are the live stack. `agentic_backend/src/` is the Python import root. Shared modules are
`config.py`, `models.py`, `search.py`, `llm.py`, `tracing.py`, `api.py`, `auth.py`, and
`db/web/sql.py`; they never import agents except `api.py`, the delivery layer, which imports
the orchestrator's graph and builders and the reporter's resume classifier. There is
no `database.py` or `prompt_logs` path; `agentic_backend/` reaches Postgres
through the LangGraph checkpointer and store and the Django-owned
`chat_threads`/`quota`/`site_quota` statements (plus a read of `users_user.is_staff`) in `db/web/sql.py` (schema
owned by `web_backend`'s migrations; guarded by
`agentic_backend/tests/integration_tests/`). The store is schema `agentic`'s
`store`/`store_migrations` tables, created by `AsyncPostgresStore.setup()` at
startup (outside Alembic, guarded by `_assert_agentic_schema`); it holds the
video-notes cache for `ask_video`, whose items expire with `api.STORE_TTL`
(30 days) and the TTL sweeper clears. The forecaster's video cache comes
through the parent's store: `orchestrator.nodes.deep_forecaster` reads
`runtime.store` and passes it into `forecast()`; concurrent asks of the same
video and question coalesce on a per-key lock in `video.watch_video`.

`web_backend/` is a second Python service (its own `pyproject.toml`, `uv.lock`, `Dockerfile`,
and `manage.py`) that owns accounts, admin, and the `chat_threads`/`quota`/`site_quota` tables. The two
services never import each other and share only the database and the root `.env`. Run its tests
from the root with `make test-web-backend` (they need the dev Postgres) and its migrations with
`make migrate-web`; its apps live under `web_backend/<app>/` with the settings module at
`web_backend/politicalagent/settings.py`, and its tests under `web_backend/tests/<app>/`. Business
rules live in each app's `services.py`; admin classes, views, mail backends, and management commands
only call a service and show its result. `web_backend/` also serves the public SEO surface:
`/robots.txt`, `/sitemap.xml`, and `/llms.txt` (the `pages` app), `/about/`, `/privacy/`, and the
admin-written Markdown posts at `/blog/` (the `blog` app); every page carries canonical and Open
Graph tags, and the landing page and blog posts carry JSON-LD, all built from `settings.SITE_ORIGIN`. Fonts are
self-hosted under `/static/site/fonts/`; nothing is loaded from Google. nginx 301s `www` to the
apex and marks `/chat` `noindex`. Django owns every user-keyed
application table in `public`; LangGraph's checkpointer tables live in the
`agentic` schema and Django never touches them. Alembic (`make migrate-agentic`)
creates the schema and moves tables into it; the checkpointer's own `setup()`
creates and migrates the tables at startup through the pool's `search_path`
(`agentic,public`). Run `make migrate-agentic` before starting the service:
startup refuses while `public.checkpoints` exists or `agentic` is not the
current schema. `agentic_backend/` reads Django's tables only through
`web_backend`-migrated schema. `web_backend`'s `checkpointer` app browses those
four tables with staff-only, read-only raw-SQL admin pages — it defines no
Django models and issues no writes; the only SQL that deletes from them stays
in `chat`.

The `emails` app owns the `emails_email` table. All Django mail goes through
`MAILERS["default"]` (the queue) and is sent by `emails.services.send_batch()`
through `MAILERS["smtp"]`; the host crontab runs
`manage.py send_queued_emails` every minute (README's "Queued email" section
has the line). All queue rules — attempts, retry wait, slice, hourly
cap — live in `emails/services.py`; the cap's value is
`settings.EMAIL_MAX_PER_HOUR`, not a services constant.

Agents live in `agentic_backend/src/agents/<name>/` with graph, state, config, prompts,
`consts/`, and node modules. Put fixed editorial data in `consts/`, prompts in
the agent's `prompts.py`, and hardcoded tuning in dataclass config. Keep all
module-level constants together at the beginning of each Python file, immediately
after imports and before functions or classes. Nodes return
partial state dictionaries without mutation.

Unit tests mirror `agentic_backend/src/`: test `src/<path>/<name>.py` in
`tests/unit_tests/<path>/test_<name>.py`, and give every test
subdirectory an empty `__init__.py`. Every test is written in
arrange/act/assert sections, marked with `# Arrange`, `# Act`, and
`# Assert` comments in that order. When the act cannot stand apart from
its assert, as a call inside `pytest.raises` cannot, one `# Act + Assert`
section holds both, and a test that asserts module surgery with no
arrangement or action may carry `# Assert` alone. A missing section is a
review-blocking defect. Frontend unit tests are Vitest in
`frontend/chat/` (`npm test` from `frontend/chat/`), not in the Python suite. Each agent's
compiled graph gets its
own `tests/unit_tests/agents/<name>/test_graph.py`.

End-to-end tests live in root `e2e/`, a Playwright project with its own pinned `package.json`; run its
commands from `e2e/`. Plain-English specs in `e2e/test_specs/` are the only files a person edits;
`e2e/tests/*.spec.ts` are generated from them by a command only the user runs (`/e2e` in Claude
Code): an agent writes or changes the spec and asks the user to regenerate the test. Generated files
start with `// spec-sha256: <hash of the spec>`. Tests run against the Compose stack at `http://localhost:8082` with
the real backend, so each spends the test user's research quota; assertions are shape checks only. The
test user comes from `make e2e-user` (the `create_e2e_user` command, which refuses unless `DEBUG` is on,
calling `users.services.ensure_e2e_user`, which also refills its quota). `e2e/check-no-password.sh` fails a
run whose artifacts hold the test password (exit 1; exit 2 when it cannot check). `.github/workflows/e2e.yml` runs the dev configuration on dispatch only and
gates nothing.

```text
START -> classify -> expert -> END
                  \-> chat   -> END
                  \-> deep_expert -> END
                  \-> deep_forecaster -> END
                  \-> reporter -> END

START -> search_and_fetch -> answer -> END

START -> research -> draft_claims -> council_round_1 -> council_round_2 -> tally -> write_analysis -> verify -> END
```

The orchestrator calls the expert, the deep expert, and the reporter from inside its own wrapper
nodes rather than adding a child graph as a node, because no child's state schema matches the orchestrator's: the expert's and the
reporter's share no key with it, and the deep expert's shares only `messages`. The forecaster's
(`agents/deep_forecaster/`) shares no key with the orchestrator's either, and is invoked the same
way. The expert makes exactly
three Brave batches, extracts allow-listed pages with trafilatura, and makes one
streamed plain-text model call. Each answer ends with a fixed next-step menu (deep dive, forecast, report, with the deep-dive and forecast costs from config.py and the report's one unit stated in expert/prompts.py), which the reporter's prompts ignore. Expert search (every Brave batch failing), source, and model failures are
hard errors; do not add degraded fallbacks.

The deep expert (`agents/deep_expert/`) is a `deepagents` agent (gpt-5-mini, `reasoning_effort="low"`). It plans, searches and reads through the shared `search.py` boundary with the expert's `EXPERT_SOURCES`, and revises under `RubricMiddleware` (gpt-4o-mini grader). The grader reads the question and the whole final draft (`graph.grader_view`), never tool output. The classifier routes to `"deep"` only after an explicit request for depth, and keeps same-topic follow-ups deep. Search is capped at 5 per turn, shared with its subagent, and a spent budget is a message to the model rather than an error. Wall time is capped at 480 s, and passing it is a hard error (`ResearchLimitError`, 504). An unsatisfied grader after 3 rounds ships the last draft. A grader crash, no source read, or no cited source is a hard error. Its graph and tools are built per turn, never at import. `research()` runs the agent with checkpointing off for its whole tree (`NO_CHECKPOINTER_CONFIG`). Its answer reaches the browser once as a `notice`, and its progress labels carry counts only.

The deep forecaster (`agents/deep_forecaster/`) is a fixed seven-step workflow, not an agent: research, drafting the claims, two council rounds, tally, writing, verification. Only `research` is autonomous — a `deepagents` lead and parallel scouts over the twelve forecasters' own sites, with `ask_video` for one forecaster's public YouTube videos — and the node returns what the scouts' tools recorded, never the lead's text. The council is seven seats, one per vendor (OpenAI, Google, Anthropic, Z.ai, DeepSeek, Qwen, Moonshot), all paid models called through OpenRouter alone (`OPENROUTER_API_KEY`; `GEMINI_API_KEY` is for `ask_video` only), whose members read only the passages the drafter points at and vote in two Delphi rounds; every verdict is counted in code, and `verify` re-renders them with the full vote list. Routing: `"forecast"` only on an explicit forecast or prediction request, never sticky — a new question after a forecast is `"geopolitical"`, and a question about the forecast is `"other"`. Wall time is capped at 840 s by `time_limits.run_under_time_limits`, which runs the forecast in its own task and cancels it repeatedly, so a stack that swallows one cancel cannot hold the turn (smoke gate F3 saw that; plain LangGraph does not); research is time-boxed at 330 s, and `draft_claims` and `write_analysis` carry per-node timeouts that are also 504s, and each forecast is charged 20 research turns. A forecast answers from `ForecastState` only — no key of it is shared with the orchestrator's — and its answer reaches the browser once as a `notice`.

The API accepts exactly one of `{query, thread_id}` or `{resume, thread_id}`.
Every `/api/*` route except `GET /api/health` requires a bearer access token minted by Django at
`GET /accounts/token/` (the `accounts_api` app; verified in `auth.py`; a failed verification is 401,
a foreign thread is 403). It rejects (422) a `query` or `resume` over 2,000 characters before collapsing its
whitespace, requires a thread id of 1 to 100 characters from `[A-Za-z0-9_-]`, and uses
an `AsyncPostgresSaver` initialized at startup. `build_graph()` remains usable
without a checkpointer for tests and Studio, and `auth.py` reads
`JWT_SIGNING_KEY` at call time, never at import, so neither can require an
identity service. The delivery layer streams only the API; nginx serves the chat SPA at `/chat`
statically and the backend serves no HTML. Stream with `custom`, `updates`,
and `messages` plus `subgraphs=True`; nodes emit their own progress through a
`StreamWriter`, and the delivery layer reads custom payloads without
filtering them by namespace (it forwards `progress` frames, turns `notice` into
answer text, and drops unknown types), because a subgraph's custom events arrive under
the child namespace while `updates` are filtered to the empty one. Emit
answer-node AI text, except for three
nodes that deliver their answer whole: the `reporter` node's refusal, cancel, and revision-cap
paths, which make no model call, the `deep_expert` node's finished analysis, and the
`deep_forecaster` node's forecast. Each emits its
own `notice` custom event and the delivery layer turns it into answer text; none of the three may
join `api.ANSWER_NODES`, and no forecaster node may be named `answer`, `chat`, or `write`. SSE events are
`progress`, `token`, `pause`, `result`, and `error`, with `result` carrying
`kind` and `truncated`; known pipeline statuses are 422, 503, 502, 504, 409, and 429, each a `PipelineError` subclass's
`status` in `models.py` (the base class is 500).
The UI sanitizes Markdown and persists the thread id in
`localStorage`. `_generate` emits at most `config.MAX_ANSWER_CHARS` (50,000) characters, marked with the
`truncated` flag, but drains upstream output so checkpoint writes finish; the
reporter's separate `MAX_REPORT_CHARS = 50_000` bounds what is stored in the
thread.

## Operations and validation

There is one root `.env`; never modify it or commit secrets. It supplies API,
tests, Studio, and Compose. API startup requires `OPENAI_API_KEY`,
`BRAVE_SEARCH_KEY`, `DATABASE_URL`, `JWT_SIGNING_KEY`, `OPENROUTER_API_KEY`, and
`GEMINI_API_KEY`; a deploy whose app fails to start prints its last 100 log lines; tracing is optional, idempotent, and
unredacted when enabled. Every custom span opens through `tracing.start_span`,
which parents it on the current LangChain run's span (the LangChain tracer
never makes its spans current). `fetch_source` (one per page fetch),
`brave_search`, `deep_research`, `forecast_research`, `evidence_positions`, and
`watch_video` carry the signals that decide whether to build a corpus
(brainstorm 2026Oct13). `session.id` comes from LangGraph's `thread_id`
metadata, and `user.id` (the raw Django id) from `tracing.bind_trace_user` in
the stream endpoint; `start_span` opens spans through `OITracer` so they carry
`user.id` too. Custom spans carry no `session.id` of their own: they sit in the
session's trace. Compose has Postgres, agentic-backend, web-backend, frontend,
and Phoenix;
development ports are 8082, 8083, 3001, 55432, and loopback 6006. Production uses TLS
and fail-closed Basic Auth for `/admin/` and `/phoenix/` — `/api/*` is guarded
by bearer JWTs (verified in `auth.py`). Production deploys only through the
dispatch-only `deploy.yml`, from `main` or a tag. It runs `tests.yml` (via
`workflow_call`), pushes the three images to GHCR as `:<sha>` and `:latest`, and
runs `deploy/vps.py` on the VPS: a pre-deploy `pg_dump`, Django then Alembic
migrations inside the containers, and `up --wait`, after which `deploy.yml` curls the public
`/api/health` and the Django landing page. `docker-compose.yml` pins `name: geopoliticai`, and each
app service carries both `build:` (dev) and `image:` (prod pulls, never
builds). Test the script with `uvx pytest deploy/tests`; ruff checks
`deploy/`. A failed deploy restores its snapshot and restarts the
previous release. `rollback.yml` restores an earlier release together with the
matching snapshot. One-way dataclass-field changes are a rollback hazard a
snapshot does not cover: a checkpoint written after `Source.author` existed
(review thread, #139) reads back on the previous image with `None` in place
of each `Source`: JsonPlusSerializer's `Source(**fields)` raises on the
unknown field and swallows the error. Every custom type stored in a
checkpoint must be in `api.CHECKPOINT_SERDE`'s msgpack allow-list (only
`models.Source` today), and a new field on it needs a default so older
checkpoints still load. `vps.py backup` uploads a nightly dump off-site. Its
credentials live in the VPS's `backup.env`, never in `.env`. The daily research quota is
`DAILY_RESEARCH_TURNS` and the site-wide ceiling `DAILY_RESEARCH_TURNS_ALL_USERS`,
both in `agentic_backend/src/config.py`; their counters are the Django-owned
`quota` and `site_quota` tables (one row per UTC day). Changing a quota number
also means its copies in `web_backend/templates/pages/landing.html` (the daily
50 is drift-tested, the forecast's 20 is not) and
`e2e/test_specs/daily-limit-is-50.md`. The
cross-service schema guards run with both integration suites
(`agentic_backend/tests/integration_tests/test_db_web_schema.py`, and the
root `make test-web-integration`; the first needs a Postgres migrated by both
`make migrate-web` and `make migrate-agentic` and fails without `DATABASE_URL`;
the second skips when the checkpointer tables are absent). Chat turns are free; a deep turn
spends `DEEP_RESEARCH_TURN_COST` and a forecast `FORECAST_TURN_COST` units (same `config.py`) from
both counters, and every other research turn one. For a costly turn an advisory per-user headroom
read runs first, so a turn it refuses touches neither counter, and `api._costly_turn_lock`
serializes each user's quota commits.

Run application commands from `agentic_backend/`: `uv sync --locked --dev`, `make test`,
`make lint` (ruff and `mypy --strict`; CI does not run it), `make format`, `make test-integration`,
and `langgraph dev`. CI (`tests.yml`) also runs `uv run python manage.py test --exclude-tag=integration`
in `web_backend/`, `npm ci && npm test && npm run build` in `frontend/chat/`, and
`uvx ruff check deploy/ scripts/` with their tests from the root.
From the root, use `make logs-SERVICE` and `make services`. Manual quality work
is `agentic_backend/evals/`: one script per eval, run from `agentic_backend/` as
`uv run python -m evals.<name>`, with judges in `evals/judges/`, shared
AX/Phoenix code in `evals/helpers/`, and examples in `evals/datasets/` (a list of
`{name, input, output}`, or `{description, cases}`); a new eval also joins `EVAL_MODULES` in
`agentic_backend/Makefile` and a step in `evals.yml`. Evals never call Brave except `e2e_deep_forecaster`, whose one example runs
Brave, page reading, and the council live (user decision 2026-10-08); expert,
deep_expert, and the recorded e2e examples carry synthetic sources, never
fetched article text. `recorded_sources` patches the expert's retrieval node,
the deep expert's tools, and the deep forecaster's tools. The `deep_expert`
eval judges its `deep_answer` with the expert's three judges and compares it
with the expert's `answer` from a live run on the same recorded sources. The
`deep_forecaster` eval's fixture carries an `as_of` date each run passes as
the forecast's `today`. Evals are advisory, outside
pytest (their helpers, judges, and datasets are unit-tested), and reachable in
CI only through the dispatch-only `evals.yml` workflow, which gates no merge; a
run exits non-zero on a task crash, a judge error, or a judge average below its
minimum (the gate is in `evals/helpers/run.py`, the minimums in `evals/helpers/judge.py`). The eval scripts require `OPENAI_API_KEY`
and `OPENROUTER_API_KEY` (the live e2e deep forecaster also requires
`GEMINI_API_KEY` for `ask_video` and uses the deployment's
`BRAVE_SEARCH_KEY`) and record their scores to
Arize AX or local Phoenix depending on
`ARIZE_PLATFORM`: `AX` uses `ARIZE_COLLECTOR_ENDPOINT`, `ARIZE_SPACE_ID`, and `ARIZE_API_KEY`, while
`PHOENIX` (the default) uses `PHOENIX_COLLECTOR_ENDPOINT` and sends no API key.

## Working principles

1. **Think before coding.** State assumptions, surface ambiguity and tradeoffs,
   ask when the intended behavior is unclear, and trace the actual flow before
   choosing an implementation.
2. **Reuse before writing.** First determine whether the behavior is needed;
   then prefer an existing local pattern, the standard library, a platform
   feature, or an installed dependency. Otherwise write the minimum code.
3. **Fix root causes with the smallest correct change.** Check related callers
   and fix shared behavior once when appropriate. Match local style, avoid
   unrelated cleanup, and remove only code made unused by your own change.
4. **Do not optimize away essential rigor.** Validate inputs at trust boundaries
   and preserve error handling that prevents data loss. Keep security,
   accessibility, and explicitly requested behavior intact.
5. **Define and verify the goal.** Non-trivial behavior changes need a focused,
   runnable test or check that fails when the logic regresses. Run the narrowest
   useful validation until it passes, and use a brief step-and-check plan for
   multi-step work.

These principles favor caution over speed; keep trivial changes proportionate.
