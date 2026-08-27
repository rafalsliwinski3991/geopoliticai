# Phoenix Tracing Plan v1 — 2026-08-26

**Derived from:** `docs/brainstorming/2026Aug26_brainstorm_v1.md` (3 rounds, closed early;
deployment model, scope, and retention all settled).

**Verified against:** the working tree on branch `2026Aug25-two-node-rewrite` —
`docker-compose.yml`, `docker-compose.override.yml`, `docker-compose.prod.yml`,
`app/pyproject.toml`, `app/Dockerfile`, `app/langgraph.json`, `app/src/api.py`,
`app/src/cli.py`, `app/src/llm.py`, `app/src/agents/expert/graph.py`.

**Goal:** self-hosted Arize Phoenix running as a compose service with persistent storage,
and the `expert` agent actually emitting spans to it — query, prompt, retrieved source
text, and model response, verbatim, no redaction.

---

## Summary

The brainstorm settled *what* to run. Two things are missing: the compose service (drafted,
then reverted) and any instrumentation at all in `app/`. This plan does both, in that order,
plus the env wiring and guidance-file updates the repo requires for every change.

| | Now | After |
| --- | --- | --- |
| Compose services | postgres, backend, frontend | + `phoenix` |
| Named volumes | `postgres_data` | + `phoenix_data` |
| Python runtime deps | 11 | 13 (`+arize-phoenix-otel`, `+openinference-instrumentation-langchain`) |
| Shared modules in `app/src` | api, cli, config, database, llm, models, search | + `tracing.py` |
| Trace visibility | `langgraph dev` Studio only, dev-time, ephemeral | persisted Phoenix UI for every run of every entrypoint |

Three rules govern the steps below:

1. **Tracing is never on the product's critical path.** The repo's "hard-fail, never degrade"
   rule (`CLAUDE.md`) governs *search and answering*. Telemetry is the deliberate exception:
   an unreachable collector, a missing dependency, or an exporter error must never fail a
   request. This is stated explicitly because it reads as a contradiction otherwise.
2. **Tracing is opt-in by environment.** With `PHOENIX_COLLECTOR_ENDPOINT` unset, `init_tracing()`
   is a no-op. Tests, CI, and a bare `python src/cli.py` stay exactly as they are today.
3. **Phoenix stays off the public internet.** No `ports:` in the base compose file; a
   loopback-bound port in the dev override only (see the deviation in Step 1).

---

## Step 1 — Add the `phoenix` compose service

**File:** `docker-compose.yml`

```yaml
  phoenix:
    image: arizephoenix/phoenix:version-11.0.0   # pin, do not use :latest
    environment:
      PHOENIX_WORKING_DIR: /mnt/data
    volumes:
      - phoenix_data:/mnt/data
```

and `phoenix_data:` under `volumes:`. `backend` gains `phoenix` in its `depends_on` list and
two environment entries (Step 5). No `ports:` mapping — Phoenix is reachable only as
`http://phoenix:6006` on the compose network.

**File:** `docker-compose.prod.yml` — add `phoenix: { restart: unless-stopped }`, matching
every other service there.

**Deviation to confirm before applying.** The brainstorm carried "Phoenix must never publish a
host port" as a flag, on the stated premise that no compose service publishes one. That premise
holds for `docker-compose.yml` but **not** for `docker-compose.override.yml`, which publishes
frontend (8082), backend (3001), and postgres (55432) for local dev. Taken literally, the flag
makes the Phoenix UI unreachable in local development without an SSH tunnel to your own machine.
Recommended resolution: publish in the **override file only**, bound explicitly to loopback:

```yaml
  phoenix:
    ports:
      - "127.0.0.1:${PHOENIX_PORT:-6006}:6006"
```

Base and prod compose stay portless, so production access remains SSH-tunnel-only, and the
no-auth flag from the brainstorm stays acceptable. If the user prefers the flag read strictly,
drop this block and tunnel in dev too — everything else in this plan is unaffected.

**Image tag.** The brainstorm draft used `:latest`. Pin a version instead: `:latest` silently
changes the trace store's schema across a `docker compose pull`, on a volume holding history
you cannot regenerate. Confirm the current tag at implementation time.

---

## Step 2 — Add the tracing dependencies

**File:** `app/pyproject.toml`, `[project].dependencies` (runtime, not dev — the backend
container installs with `--no-dev`):

```
"arize-phoenix-otel>=0.6,<1.0",
"openinference-instrumentation-langchain>=0.1,<1.0",
```

`arize-phoenix-otel` is the thin client-side registration package (OTel SDK + OTLP exporter);
it does **not** pull the Phoenix server into the image. The OpenInference LangChain
instrumentor is what turns LangChain/LangGraph callbacks into spans — it covers `ChatOpenAI`
calls and every LangGraph node, which is why no code change to `llm.py` or the nodes is needed.

Then, from `app/`: `uv lock` and `uv sync --locked --dev`. CI installs from `app/uv.lock`, so
the lockfile must be committed in the same change.

Verify the exact current version bounds against the packages at implementation time rather
than trusting these ranges.

---

## Step 3 — Add `app/src/tracing.py`

A new **shared** module (imports nothing from `agents/`, per the repo's one invariant). One
public function, idempotent, exception-swallowing, no-op when unconfigured:

```python
"""OpenTelemetry boundary: optional Phoenix span export."""

def init_tracing() -> bool:
    """Register Phoenix tracing when configured; never raise.

    Returns True when tracing was activated by this call.
    """
```

Behaviour:

- Read `PHOENIX_COLLECTOR_ENDPOINT`. Empty or unset → log at DEBUG, return `False`.
- Guard with a module-level `_initialized` flag so repeated calls (API lifespan + graph import
  in the same process) register once.
- Call `phoenix.otel.register(endpoint=..., project_name=os.getenv("PHOENIX_PROJECT_NAME", "geopoliticai-expert"), auto_instrument=True)`.
  `auto_instrument=True` picks up the installed OpenInference LangChain instrumentor.
- Wrap the whole body in `except Exception` → `logger.warning("Tracing disabled: %s", exc)`,
  return `False`. This is the Rule 1 exception, and the module docstring should say so.

Add `"tracing"` to `py-modules` in `app/pyproject.toml` (that list is explicit).

Note on span content: OpenInference records prompt and completion content by default, which is
exactly the settled "full raw content, no redaction" decision. Do **not** set
`OPENINFERENCE_HIDE_INPUTS`/`HIDE_OUTPUTS`. If that decision is ever revisited, those env vars
are the single lever — no code change.

---

## Step 4 — Call `init_tracing()` at the entry surfaces

Three processes can run the graph. Each needs one call:

1. **`app/src/api.py`** — first line of the `lifespan` body, after `init_environment()` and
   before `require_env()`.
2. **`app/src/cli.py`** — in `main()`, after `init_environment(...)`.
3. **`app/src/agents/expert/graph.py`** — module scope, immediately before `graph = build_graph()`,
   so `langgraph dev` (which imports this module directly and never runs our entrypoints) also
   exports spans.

Call 3 is an import-time side effect, which the repo otherwise avoids. It is accepted here
because it is the only hook `langgraph dev` gives us, and because the function is a no-op
without the env var — importing `graph.py` in a unit test does nothing. The alternative
(leaving `langgraph dev` on Studio only) is a legitimate simplification if the user would
rather keep module imports pure; flag it, don't decide it silently.

Nothing else changes. `llm.py`, `search.py`, and the two nodes are untouched.

**Not instrumented:** the Brave and trafilatura `httpx` calls in `search.py`. No HTTP-level
instrumentation is added in v1 — the fetched source text is already visible in Phoenix as the
answer node's prompt input, which satisfies the settled scope. Adding
`opentelemetry-instrumentation-httpx` later would give per-request search timing; out of scope
here.

---

## Step 5 — Environment wiring

- `docker-compose.yml`, `backend.environment`:
  `PHOENIX_COLLECTOR_ENDPOINT: http://phoenix:6006` and
  `PHOENIX_PROJECT_NAME: geopoliticai-expert`.
- `.env.example`: add both keys, commented, with the local-dev value
  `http://localhost:6006` and a note that leaving them unset disables tracing entirely. Add
  `PHOENIX_PORT` alongside the other `*_PORT` overrides if Step 1's dev port block is kept.
- `.env`: not touched by this plan (repo rule). The user sets it if they run outside compose.
- `config.py`: **not** modified. It holds OpenAI/model configuration; the Phoenix endpoint is
  read in `tracing.py`, keeping the telemetry boundary self-contained.
- `app/langgraph.json`: no change — it already loads `../.env`, so `langgraph dev` picks up
  the endpoint from the same file.

---

## Step 6 — Tests

`app/tests/unit_tests/test_tracing.py`, offline only:

1. Unset endpoint → `init_tracing()` returns `False`, registers nothing, does not raise.
2. Endpoint set to an unroutable address, `phoenix.otel.register` monkeypatched to raise →
   returns `False`, logs a warning, does not raise. This is the regression test for Rule 1.
3. Endpoint set, `register` monkeypatched to a spy → called once with the expected project
   name; a second `init_tracing()` call does not call it again (idempotency).

No integration test: asserting against a live Phoenix container is not worth a new service
dependency in `make integration_tests`. Manual verification covers it (below).

---

## Step 7 — Guidance files

`CLAUDE.md` requires `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` to be
updated together. Add to each, in that file's own voice:

- `app/src/` now includes a `tracing.py` boundary — optional, env-gated, never fails a request.
- Compose runs a `phoenix` service on the internal network with a `phoenix_data` volume;
  it publishes no host port outside the dev override.
- `PHOENIX_COLLECTOR_ENDPOINT` / `PHOENIX_PROJECT_NAME` are the only tracing switches; unset
  means no tracing.

---

## Verification

Run in order; each line is a pass/fail gate.

1. `cd app && uv sync --locked --dev` — lockfile matches `pyproject.toml`.
2. `make lint && make test` — mypy `--strict` covers the new module; unit tests green.
3. `docker compose config` — `phoenix` present, `phoenix_data` declared, and **no `ports:`
   under `phoenix`** when the override is excluded (`docker compose -f docker-compose.yml config`).
4. `docker compose up -d` then `docker compose exec backend .venv/bin/python -c "import urllib.request; print(urllib.request.urlopen('http://phoenix:6006').status)"` — backend can reach Phoenix.
5. One real query through `POST /api/run_pipeline` (or the UI). Then open the Phoenix UI and
   confirm a trace exists for project `geopoliticai-expert` with: the graph run as root, one
   span per node (`search_and_fetch`, `answer`), and the `answer` LLM span carrying the full
   system prompt, the fetched source text, and the streamed response.
6. `docker compose restart phoenix` — that trace is still listed. Proves the volume works.
7. Unset `PHOENIX_COLLECTOR_ENDPOINT`, rerun the query — succeeds, one DEBUG line, no traces,
   no errors. Proves Rule 2.
8. `docker compose stop phoenix`, rerun the query with the endpoint still set — the request
   still returns a normal answer. Proves Rule 1.

Gates 7 and 8 are the ones that matter; skipping them is how tracing quietly becomes a new
way for the product to fail.

---

## Rollback

Every piece is independently revertible: unset the two env vars (tracing off, code inert),
`docker compose rm -sv phoenix` (service gone), `docker volume rm geopoliticai_phoenix_data`
(history gone — irreversible), or revert the commit (deps and `tracing.py` gone). No data
migration, no schema change, no change to any existing request path.

---

## Risks and open items

- **No auth on the Phoenix UI.** Carried from the brainstorm. Acceptable only while it stays
  unpublished/loopback-only. The blast radius is every query and every fetched page ever
  processed. Revisit the moment anyone wants remote access without a tunnel — Phoenix supports
  `PHOENIX_ENABLE_AUTH` with a secret, which is the fix, not a proxy.
- **Nothing enforces the no-published-port rule.** A future edit to `docker-compose.yml` could
  add `ports:` and no test would notice. Verification gate 3 is manual. A CI grep over
  `docker-compose.yml` would close this; not included here.
- **Volume growth is unbounded.** "Retention: persisted" was settled without a ceiling, and
  full raw page text is the bulkiest thing this app handles. Watch `phoenix_data`; Phoenix has
  no built-in TTL configured by this plan.
- **`phoenix_data` is not in any backup.** Neither is `postgres_data` today, so this is
  consistent, not a regression — worth naming.
- **Version drift.** The two Python packages and the Phoenix image must stay roughly in step;
  the OTLP wire protocol is stable, so drift shows up as missing attributes rather than
  breakage. Pin all three.
- **Open decision:** dev-only loopback port (Step 1) — recommended, needs the user's yes.
- **Open decision:** import-time `init_tracing()` in `graph.py` (Step 4) — the only way to
  trace `langgraph dev`; drop it if import purity matters more.
