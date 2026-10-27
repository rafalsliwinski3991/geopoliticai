# CLAUDE.md

<!--
Maintainers: a line belongs here only if agents need it across tasks and cannot learn it from the
code, its config, or another guidance file. Name a constant instead of copying its value. Changes to
harness tooling (commands, skills, agents, plugins) need no update here. AGENTS.md is a symlink to
this file, so OpenCode, Copilot, and Antigravity read it too: name no tool or path that only one harness has.
-->

## Working rules

- Make the smallest correct change. Reuse a local pattern, the standard library, or an installed
  dependency before writing code; fix a shared root cause once; leave unrelated code alone and
  remove only what your change made unused.
- Pipeline failures raise a `PipelineError` subclass (`models.py`) whose `status` the API reports.
  Answer with the error, never with a degraded fallback.
- A behaviour change needs a focused test that goes red when the logic regresses. Run the narrowest
  check until it passes, then the area's suite below.
- Keep all module-level constants together after the imports, before any function or class.
- The root `.env` supplies the API, tests, Studio, and Compose. Never read, print, or modify it, and
  never commit a secret.

## Commands

- From `agentic_backend/`: `uv sync --locked --dev`, `make test`, `make lint` (ruff and
  `mypy --strict`; CI does not run it), `make format`, `langgraph dev`, and `make test-integration`
  (needs a Postgres migrated by `make migrate-web` and `make migrate-agentic`).
- From the root: `make test-web-backend` (needs the dev Postgres), `make test-web-integration`,
  `make migrate-web`, `make migrate-agentic`, `make e2e-user`, `make logs-SERVICE`; `make help`
  lists the rest.
- CI (`tests.yml`) also runs `uv run python manage.py test --exclude-tag=integration` in
  `web_backend/`, `npm ci && npm test && npm run build` in `frontend/chat/`, and, from the root,
  `uvx ruff check deploy/ scripts/` and `uvx --with pydantic --with openai pytest deploy/tests scripts/tests`.

## Layout

- `agentic_backend/` is the FastAPI app (import root `src/`), serving only the API. `web_backend/` is
  the Django service that owns accounts, admin, the public pages, and every user-keyed table.
  `frontend/chat/` is the chat SPA, served statically by nginx at `/chat`. The two Python services
  never import each other; they share only Postgres and the root `.env`.
- The root `docker-compose*.yml` files are the live stack (`build:` for dev, `image:` for production,
  which only pulls). The root `Dockerfile` and `requirements.txt` are unused compatibility files;
  re-export `requirements.txt` (command in its header) whenever `agentic_backend/uv.lock` changes.

```text
orchestrator     START -> supervisor -> tools | END (a chat answer);  tools -> supervisor -> END
                 tools -> END (on run_reporter)
expert           START -> search_and_fetch -> answer -> END
reporter         START -> outline -> gate | END;  gate -> outline | write | END;  write -> END
deep_forecaster  START -> research -> draft_claims -> council_round_1 -> council_round_2
                      -> tally -> write_analysis -> verify -> END
                      verify -> write_analysis (once, on a defect)
```

## Naming

- Python functions are verb-first (`start_span`), except tests, which the `unit-tests` skill names
  as sentences, and a pure getter whose siblings are nouns (`quota_day` beside `quota_used`). Types
  and test fakes are nouns (`ExtractedPage`, `RecordingQuota`), module constants are UPPER_SNAKE
  (`TRACER_NAME`), and no name ends in `_helper` or `_util`.
- Span names are snake_case (`fetch_source`); span attribute keys are dotted with a domain prefix
  (`source.outcome`).
- TypeScript functions are camelCase and verb-first (`warnOnStaleTests`); an e2e spec and its
  generated test share one kebab-case stem that starts with its group: `agent-`, `ui-`, `auth-`
  or `site-`.
- An eval's script, dataset, and judges file share one name: its agent, then `_fixed` when the
  agent's inputs are written in advance or `_live` when it searches and reads today's pages
  (`expert_fixed`, `expert_live`).

## agentic_backend

- The shared modules (`config.py`, `models.py`, `search.py`, `llm.py`, `tracing.py`, `api.py`,
  `auth.py`, `quota.py`, `frames.py`, `db/web/sql.py`) import no agent, except `api.py`, the delivery layer, which imports
  the orchestrator's graph and builders and the reporter's resume classifier.
- Besides the LangGraph checkpointer and store, the only Postgres access is the raw SQL in
  `db/web/sql.py` against Django-owned tables, whose schema only `web_backend`'s migrations change;
  the integration tests guard it.
- The checkpointer's and the store's tables live in the `agentic` schema. Alembic
  (`make migrate-agentic`) creates the schema and moves tables into it; each library's `setup()`
  creates its tables at startup through the pool's `search_path` (`agentic,public`). Run
  `make migrate-agentic` before starting the service: startup refuses while `public.checkpoints`
  exists or `agentic` is not the current schema.
- Every custom type stored in a checkpoint must be in `api.CHECKPOINT_SERDE`'s msgpack allow-list
  (only `models.Source` today), and a new field on it needs a default. A field change is a rollback
  hazard a database snapshot does not cover: the previous image's `Source(**fields)` raises on the
  unknown field, and JsonPlusSerializer silently reads back `None` in place of each `Source`.
- The store holds only `ask_video`'s video-notes cache, expiring after `api.STORE_TTL`; the
  forecaster reaches it through the orchestrator tool's `runtime.store`.
- `build_graph()` works without a checkpointer (tests, Studio), and `auth.py` reads
  `JWT_SIGNING_KEY` at call time. API startup requires `config.REQUIRED_ENV_VARS` and `DATABASE_URL`.
- Record every decision agent code makes (a retry, a drop, a cap reached, a verdict) as attributes
  on a custom span: counts, outcomes, reasons, timings, and the model that answered, so a Phoenix
  trace alone explains a run. Open each span with `tracing.start_span`, which parents it on the
  current LangChain run's span (that tracer never makes its spans current) and adds `user.id`. Keep
  the attributes on the `fetch_source`, `brave_search`, `deep_research`, `forecast_research`,
  `evidence_positions`, and `watch_video` spans: they will decide whether to build a source corpus.

## Agents

- Each agent lives in `agentic_backend/src/agents/<name>/`: fixed editorial data in `consts/`,
  prompts in `prompts.py`, tuning in its config dataclasses (`LIMITS`, the `*_LLM_SETTINGS`). Nodes
  return partial state dicts without mutating state.
- The orchestrator coordinates specialists via modular tools (`agents/orchestrator/tools/`) executed
  in a `ToolNode(ALL_TOOLS, handle_tool_errors=False)` that update the `expert_synthesis` and `forecast_data`
  channels on `OrchestratorState`, so a failing tool raises to the API's error frame.
- Routing: In supervisor Pass 1, conversational small talk is answered directly without tools. Geopolitical
  queries route to specialist tools: `deep` (`run_deep_expert`) only after an explicit request for depth, and
  same-topic follow-ups stay deep; `forecast` (`run_deep_forecaster`) only on an explicit forecast or prediction
  request, never sticky: a new question after a forecast is `geopolitical`, a question about the forecast `other`.
  `SUPERVISOR_SYSTEM_PROMPT` states each of these rules.
- Next-steps footer: After specialist tool execution, supervisor Pass 2 generates a dynamic next-steps footer
  offering follow-up options with canonical turn costs from `config.py`, falling back to `STATIC_NEXT_STEPS_MENU`
  on failure, emitted as a notice chunk.
- Expert: exactly three Brave batches (one failing is skipped, all failing is an error), allow-listed
  pages through trafilatura, and one streamed model call.
- Deep expert: a `deepagents` agent built per turn, never at import. It searches through
  `search.py` with `EXPERT_SOURCES` and revises under deepagents' `RubricMiddleware`, whose grader
  sees only the question and the final draft (`graph.grader_view`). A spent search budget is a
  message to the model; the wall cap is a 504 (`capped_run.run_under_time_limits`, the same
  dedicated-task cancel as the forecaster's); an unsatisfied grader ships the last draft; a grader
  crash, no source read, or no cited source is an error. `capped_run.NO_CHECKPOINTER_CONFIG` sets
  LangGraph's private `__pregel_checkpointer` key: re-check it on every langgraph upgrade.
- Deep forecaster: a fixed workflow with one backward edge. Only `research` is autonomous (a
  deepagents lead and scouts over the forecasters' sites, plus `ask_video`), and it returns what
  the scouts' tools recorded, never the lead's text. The council, one paid model per vendor through
  OpenRouter, reads only the passages the drafter points at and votes in two Delphi rounds; in
  round 1 a member whose answer cannot be counted is asked once more with the problem named, and
  round 1 then needs `LIMITS.quorum` ballots (a `QuorumError` whose `outside` says whether every
  drop was a provider outage; a refused 4xx request is ours); code
  counts every verdict; the writer sees no URL and cites sources by number (`[anchor](source:N)`),
  and `verify` puts in the URLs. `verify` sends an analysis with a defect back to the writer once,
  with the defect named; a second defect, or an answer over the delivery cap, is a hard error. `draft_claims` re-drafts once
  the same way, inside the node, when a claim breaks a rule. The wall
  cap runs the forecast in its own task (`capped_run.run_under_time_limits`) and cancels it
  repeatedly, because smoke gate F3 saw a hung run outlive an in-frame `asyncio.timeout`.
  `nodes.research` registers a deepagents harness profile that switches the default
  `general-purpose` helper off for gpt-5-mini, process-wide; another agent on that model that
  wants the helper passes its own `general-purpose` spec, as the deep expert does.

## API and streaming

- A request carries exactly one of `{query, thread_id}` or `{resume, thread_id}`. Every `/api/*`
  route except `GET /api/health` needs a bearer token minted at Django's `GET /accounts/token/`
  (`accounts_api`); `auth.py` answers a failed check with 401 and a foreign thread with 403.
- Stream `custom`, `updates`, and `messages` with `subgraphs=True`; nodes emit `frames.ProgressFrame`
  and `frames.NoticeEvent` through a `StreamWriter`. Read custom events from every namespace (a subgraph's arrive under the child's)
  and `updates` from the root only.
- Answer text streams from the AI messages of `api.ANSWER_NODES` (`answer`, `supervisor`, `write`); the
  supervisor returns a chat answer whole. The reporter's refusal, cancel, and revision-cap paths, the deep
  expert, and the forecaster deliver their answer whole as a `notice` event instead. The reporter's
  `outline`/`gate`, the deep expert, the forecaster, and `tools` may never join `ANSWER_NODES` (the text
  would print twice); the supervisor's footer starts with `config.FOOTER_PREFIX` and is skipped. No
  forecaster node may be named `answer`, `supervisor`, or `write`.

## Quota

- `DAILY_RESEARCH_TURNS` caps one user's day and `DAILY_RESEARCH_TURNS_ALL_USERS` the site's
  (`config.py`), counted in the Django-owned `quota` and `site_quota` tables per UTC day. Chat turns
  are free, a deep turn spends `DEEP_RESEARCH_TURN_COST`, a forecast `FORECAST_TURN_COST`, and any
  other research turn one unit. A costly turn refused before the site's charge
  touches neither counter; when the site's charge commits and the user's upsert
  then loses the race, the site's units stay spent and the user's counter is
  untouched. A turn that ends in an error frame gives the user's units back to
  the charge day, up to `MAX_DAILY_REFUND_UNITS` per user
  per UTC day (counted in process memory); a disconnect gives nothing back, and site units stay
  spent.
- `quota.py` holds these rules; `api._generate` only calls `charge_turn` and `refund_turn`.
- A quota number has copies in `web_backend/templates/pages/landing.html` (the daily limit is
  drift-tested, the forecast's cost is not) and `e2e/test_specs/ui-daily-limit-is-50.md`.

## web_backend

- A separate uv project. Apps live in `web_backend/<app>/` and their tests in
  `web_backend/tests/<app>/`. Business rules live in each app's `services.py`; admin classes, views,
  mail backends, and management commands only call a service and show its result.
- Canonical, Open Graph, and JSON-LD tags are built from `settings.SITE_ORIGIN`; fonts are
  self-hosted under `/static/site/fonts/`; nginx 301s `www` to the apex and marks `/chat` `noindex`.
- The `checkpointer` app only reads the checkpointer's tables, in staff-only raw-SQL admin pages; the
  only SQL that deletes from them is in the `chat` app.
- All Django mail is queued through `MAILERS["default"]` and sent by `emails.services.send_batch()`
  through `MAILERS["smtp"]` when the host crontab runs `manage.py send_queued_emails` (README,
  "Queued email"). Every queue rule lives in `emails/services.py`; the hourly cap's value is
  `settings.EMAIL_MAX_PER_HOUR`.

## Tests

- In `agentic_backend/`, unit tests mirror the source: `src/<path>/<name>.py` is tested in
  `tests/unit_tests/<path>/test_<name>.py`, every test directory has an `__init__.py`, and each
  agent's compiled graph has its own `test_graph.py`. Frontend unit tests are Vitest in
  `frontend/chat/`. Every test follows the `unit-tests` skill, including its review-blocking
  `# Arrange`, `# Act`, and `# Assert` sections.
- End-to-end tests are a Playwright project in `e2e/`; run its commands from there. People edit only
  the plain-English specs in `e2e/test_specs/`. The `e2e/tests/*.spec.ts` files are generated from
  them by a command only the user runs (README, "End-to-end tests"), so an agent edits the spec
  and asks the user to regenerate the test. The tests hit the real Compose stack, spending the test user's
  quota (`make e2e-user` creates the user and refills it), and check shapes only.

## Evals

- `agentic_backend/evals/` holds one script per eval, run from `agentic_backend/` as
  `uv run python -m evals.<name>`; `make evals-fixed`, `make evals-live`, and `make evals` (both) run
  them by kind. A new eval joins `FIXED_EVALS` or `LIVE_EVALS` in `agentic_backend/Makefile` and gets
  a step in `evals.yml` under its kind.
- The runner reads an eval's kind from its name. A fixed eval (`*_fixed`) feeds the agent inputs
  written in advance: conversations, typed replies, and recorded, synthetic pages that
  `replay_sources` puts in place of the expert's and the deep expert's retrieval, never fetched
  article text. A live eval (`*_live`) needs the Brave key and reads today's pages:
  `expert_live` and `deep_expert_live` on hand-written questions about settled past events (the deep
  eval's expert baseline answers from up to `RETRIEVAL.keep_sources` of the pages the deep run
  read, in the order read, kept by `record_sources` under the URLs the deep expert cites and
  replayed by `replay_sources`), `deep_forecaster_live` on questions
  users asked, under the forecast's wall cap. The models are called live in both.
- A dataset is `{description, cases}`; a case has `name`, `description`, `input` (keys `query`,
  `messages`, `sources`, `replies`), and, in a fixed eval only, `expected`, whose present keys are
  the checks; `test_datasets.py` fails on a key the eval's judges do not list in `EXPECTED_KEYS`. A
  failed live run is a report row judged by `finished_or_outside` (`outside` only for a provider
  outage), not a crash.
- Evals report to Phoenix only; each experiment's traces land in that experiment's own project
  (Phoenix's experiment runner sets it), never in the app's. The CI run reaches the VPS Phoenix
  through nginx Basic Auth, with the header in `PHOENIX_CLIENT_HEADERS` on the eval steps only.
- Evals are advisory: outside pytest (their helpers are unit-tested), run in CI only by the
  dispatch-only `evals.yml` (`type`: fixed, live, or all), and exit non-zero on a crash, a judge
  error, or a low judge average.

## Deploy

- Production deploys only through the dispatch-only `deploy.yml`, from `main` or a tag, and
  `rollback.yml` restores an earlier release with its matching database snapshot. The README's
  "Deploy order" and "Production deploy" sections hold the steps.
- `deploy/vps.py` is tested with `uvx pytest deploy/tests`. `vps.py backup` takes its off-site
  credentials from the VPS's `backup.env`, never from `.env`.
