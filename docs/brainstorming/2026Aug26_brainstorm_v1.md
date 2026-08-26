# Free LangGraph tracing tool

**Started:** 2026-08-26
**Status:** Closed early (1 question left open — Q3 retention, implicitly settled as "persisted" by adding Phoenix as a compose service with a data volume)
**Mode:** one question at a time

## Target design

Self-hosted Arize Phoenix, to be added as a `phoenix` service in `docker-compose.yml` on the internal network only (no published host port), backed by a named volume (`phoenix_data`) for persistent trace storage, capturing full raw LLM observability (queries, fetched source text, prompts, responses — no redaction). **Not yet implemented** — a compose edit was drafted and then reverted at the user's request; the change is wanted but not applied. The app itself is also not yet instrumented to emit traces to it.

## Context verified

- No tracing tool is currently wired into `app/` — no `langsmith`/`langfuse`/`otel` deps, env vars, or client code found in `app/pyproject.toml`, `.env.example`, or source. Only skill docs (`.claude/skills/langsmith-online-eval-engineering/`) reference LangSmith, unused.
- `app/langgraph.json` defines a single graph `expert`, dependencies `["."]`, env at `../.env`. Running `langgraph dev` already gives a local LangGraph Studio UI (graph visualization + run trace inspector) with zero extra setup — this is a real "free tool" option, not just SaaS/self-hosted alternatives.
- Repo already runs Docker Compose with a Postgres service (`POSTGRES_PASSWORD` → `DATABASE_URL`), so self-hosting another container alongside it is low-friction infra-wise, but CLAUDE.md's philosophy is "keep changes local," minimal moving parts.
- Expert graph is `START -> search_and_fetch -> answer -> END`, state is `query, sources, answer` — small graph, so tracing needs are about LLM/search call visibility more than complex branching logic.

- MLflow supports LangGraph tracing via `mlflow.langchain.autolog()` (extension of its LangChain integration) — free, open source, self-hostable, backend store can reuse the repo's existing Postgres instead of adding a separate DB. Confirmed via MLflow docs, current as of May 2026.
- Arize Phoenix core is free at $0 for self-hosted use, local or production, no usage caps or feature gating (Elastic License 2.0 — source-available, not OSI open-source, only matters if reselling Phoenix itself as a hosted service). Paid AX Pro ($50/mo) is only for their managed cloud hosting, not required for self-hosted use. Self-hosting still means you own uptime/scaling/backups of the trace store in production — same ops cost class as Langfuse OSS or MLflow.

## Settled decisions

- **Deployment model: self-hosted Arize Phoenix** — free, no usage caps, self-hosted for local dev and production alike; separate container from the app's existing Postgres. _(rationale: purpose-built LLM tracing UI, lighter than Langfuse OSS's Postgres+ClickHouse+Redis stack, no cloud/free-tier volume caps)_
  - Challenged on: is running a dedicated trace store worth it for a 3-node graph, vs. relying on `langgraph dev`'s free built-in Studio and adding Phoenix later only if needed → held, user confirmed Phoenix now.
- **Scope: full LLM observability, full raw content retained as-is** — query, fetched source text, prompt, and model response all stored verbatim in Phoenix (no redaction/masking). _(rationale: no setup-effort savings from scoping down since Phoenix auto-instrumentation captures full span content by default either way)_
  - Challenged on: no-auth-by-default Phoenix UI means the trace store's blast radius equals every query/source page ever processed → held, with the explicit constraint that Phoenix must never be exposed beyond localhost / the internal Docker network — matches the fact that no existing service in `docker-compose.yml` publishes a host port, so this isn't a new exception to the deployment pattern.
- **Retention: persisted** (implicit) — added as a long-running compose service backed by a named volume (`phoenix_data`), not ephemeral/local-only.
  - Not separately challenged; follows directly from choosing self-hosted Phoenix as a service.

## Design tree

- Tracing tool for LangGraph — OPEN
  - Deployment model — SETTLED: self-hosted Arize Phoenix
  - Scope: full LLM observability vs graph-flow visualization only — OPEN
  - Retention: persisted trace history vs ephemeral dev-time only — OPEN

## Current frontier (open questions)

_(empty — session closed early once user moved to implementation; Q3 retention resolved implicitly, see Settled decisions)_

## Carried as flags, not decisions

- **Phoenix must never publish a host port in `docker-compose.yml`** (no `ports:` mapping) — access only via internal Docker network from `backend`, or an SSH tunnel for manual inspection. Not yet enforced by any automated check; verify at deploy time.
- **Backend is not yet instrumented to send traces to Phoenix.** Adding the compose service does not wire `app/` to emit OTel/OpenInference spans — that requires adding tracing deps + `mlflow`/`openinference` style autolog/instrumentation call in the app, which was not part of this session's scope.
- **No auth is configured on the Phoenix UI.** Acceptable only as long as it stays unpublished/internal; revisit if it's ever exposed more broadly.
- **Docker Compose change wanted but not applied.** Design settled on adding a `phoenix` service (image `arizephoenix/phoenix:latest`, `PHOENIX_WORKING_DIR=/mnt/data`, `phoenix_data` named volume, no published port) — a first draft was written to `docker-compose.yml` then reverted per the user's request. Re-apply when the user is ready to actually make this change.

## Round log

### Round 1
Posed Q1 (deployment model), Q2 (scope), Q3 (retention) — see Current frontier for full text and leans.
User asked about MLflow and Phoenix pricing/self-hosting; researched both, folded into Q1 options. User switched to one-question-at-a-time mode.

### Round 2
**Q1 — Deployment model.** Asked local-only vs self-hosted (MLflow/Langfuse/Phoenix) vs cloud SaaS. Lean was Langfuse OSS. **User answered:** Phoenix. **Pushed back on** whether a dedicated trace store is worth the ops cost for a 3-node graph vs. free local Studio → held, Phoenix confirmed.

### Round 3
**Q2 — Scope.** Asked full LLM observability vs graph-flow-only visualization. Lean was full observability. **User answered:** full. **Pushed back on** raw prompt/source/response content landing in an unauthenticated-by-default Phoenix UI → user asked for deeper explanation twice; held on full raw content, with the explicit constraint that Phoenix stays unpublished/internal-network-only, matching the fact that no other compose service publishes a host port.

User then asked to implement directly ("just add this as a service to docker compose") rather than continue to Q3. Session closed early: added `phoenix` service to `docker-compose.yml` (image `arizephoenix/phoenix:latest`, `PHOENIX_WORKING_DIR=/mnt/data`, `phoenix_data` named volume, no published ports). Q3 (retention) resolved implicitly by this choice — see Settled decisions.
