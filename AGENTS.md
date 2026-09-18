# AGENTS.md

Update this file only for changes to the application codebase. Changes to
AI-harness tooling (Claude commands, skills, agents, plugins, and similar
configuration) do not require updating it.

## Application

`agentic_backend/` is the maintained application; root Docker and requirements files are
compatibility files. `agentic_backend/src/` is the Python import root. Shared modules are
`config.py`, `models.py`, `search.py`, `llm.py`, `tracing.py`, and `api.py`;
they never import agents except `api.py`, the delivery layer, which imports
the compiled orchestrator graph and the reporter's resume classifier. There is
no `database.py` or `prompt_logs` path;
Postgres is only the LangGraph checkpointer and uses `psycopg[binary]`.

Agents live in `agentic_backend/src/agents/<name>/` with graph, state, config, prompts,
`consts/`, and node modules. Put fixed editorial data in `consts/`, prompts in
the agent's `prompts.py`, and hardcoded tuning in dataclass config. Keep all
module-level constants together at the beginning of each Python file, immediately
after imports and before functions or classes. Nodes return
partial state dictionaries without mutation. Preserve shared-to-agent imports.

Unit tests mirror `agentic_backend/src/`: test `src/<path>/<name>.py` in
`tests/unit_tests/<path>/test_<name>.py`, and give every test
subdirectory an empty `__init__.py`. Frontend unit tests live in
`frontend/tests/` as `.mjs` files using the Node built-in test runner
(`npm test` from `frontend/`), not in the Python suite. Each agent's compiled graph gets its
own `tests/unit_tests/agents/<name>/test_graph.py`.

```text
START -> classify -> expert -> END
                  \-> chat   -> END
                  \-> reporter -> END

START -> search_and_fetch -> answer -> END
```

The orchestrator invokes the expert and the reporter from their own nodes, not
with `add_node`, because neither child's state schema shares a key with the
orchestrator's. The expert makes exactly
three Brave batches, extracts allow-listed pages with trafilatura, and makes one
streamed plain-text model call. Expert search, source, and model failures are
hard errors; do not add degraded fallbacks.

The API accepts exactly one of `{query, thread_id}` or `{resume, thread_id}`.
It normalizes/caps both `query` and `resume` at 2,000 characters, validates a
required thread id of at most 100 characters, and uses
an `AsyncPostgresSaver` initialized at startup. `build_graph()` remains usable
without a checkpointer for tests and Studio. Stream with `custom`, `updates`,
and `messages` plus `subgraphs=True`; nodes emit their own progress through a
`StreamWriter`, and the delivery layer forwards custom payloads without
filtering them by namespace, because a subgraph's custom events arrive under
the child namespace while `updates` are filtered to the empty one. Emit
answer-node AI text, except that the `reporter` node's refusal, cancel, and
revision-cap paths make no model call: that node emits its own `notice` custom
event and the delivery layer turns it into answer text. SSE events are
`progress`, `token`, `pause`, `result`, and `error`, with `result` carrying
`kind` and `truncated`; known pipeline statuses are 422, 503, 502, and 409.
The UI sanitizes Markdown and persists the thread id in
`localStorage`. `_generate` emits at most 50,000 characters, marked with the
`truncated` flag, but drains upstream output so checkpoint writes finish; the
reporter's separate `MAX_REPORT_CHARS = 50_000` bounds what is stored in the
thread.

## Operations and validation

There is one root `.env`; never modify it or commit secrets. It supplies API,
tests, Studio, and Compose. API startup requires `OPENAI_API_KEY`,
`BRAVE_SEARCH_KEY`, and `DATABASE_URL`; tracing is optional, idempotent, and
unredacted when enabled. Compose has Postgres, agentic-backend, frontend, and Phoenix;
development ports are 8082, 3001, 55432, and loopback 6006. Production uses TLS
and fail-closed Basic Auth for `/` and `/api/`.

Run application commands from `agentic_backend/`: `uv sync --locked --dev`, `make test`,
`make lint`, `make format`, and `langgraph dev`.
From the root, use `make logs-SERVICE` and `make services`. Manual quality work
is `agentic_backend/evals/`: one script per eval, run from `agentic_backend/` as
`uv run python -m evals.<name>`, with judges in `evals/judges/`, shared
AX/Phoenix code in `evals/helpers/`, and `{name, input, output}` examples in
`evals/datasets/`. Evals never call Brave; expert and e2e examples carry
synthetic sources, never fetched article text. Evals are advisory, outside
pytest (their helpers, judges, and datasets are unit-tested), and reachable in
CI only through the dispatch-only `evals.yml` workflow, which gates no merge; a
run exits non-zero on a task crash, a judge error, or a judge average below its
minimum (`evals/helpers/judge.py`). The eval scripts require `OPENAI_API_KEY`
and `OPENROUTER_API_KEY` and record their scores to
Arize AX or local Phoenix depending on
`ARIZE_PLATFORM`: `AX` uses `ARIZE_SPACE_ID` and `ARIZE_API_KEY`, while
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
