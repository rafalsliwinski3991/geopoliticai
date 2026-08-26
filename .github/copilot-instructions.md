# Copilot Instructions

After every codebase change, update `AGENTS.md`, `CLAUDE.md`, and this file
together. The maintained application is under `app/`; root files are
compatibility entrypoint, Docker, and requirements-export files. CI runs
`uv sync --locked --dev` in `app/` and does not reference root requirements.

Shared modules under `app/src/` provide environment/model config, shared models
and errors, policy-parameterized Brave/fetch/extraction, OpenAI access, and
delivery. Agent packages under `app/src/agents/<name>/` contain graph, state,
source policy, and node modules. Shared modules never import agents; only API
and CLI name `agents.expert`.

The expert graph is:

```text
START -> search_and_fetch -> answer -> END
```

State has exactly `query`, `sources`, and `answer`, with no reducers. The expert
policy is English-only and search performs exactly three Brave batches followed
by allow-listed page extraction with trafilatura. One streamed plain-text LLM
call produces the answer. Search, source, and LLM failures are hard errors;
there are no deterministic fallbacks. `app/langgraph.json` exposes `expert`.

The API accepts only `{query}`, normalizes and caps it at 2,000 characters, and
provides sync/SSE routes with 422/503/502 mappings for known failures. The
frontend sanitizes Markdown before `x-html`.

Run `uv sync --locked --dev`, `make test`, `make integration_tests`, and
`make lint` from `app/`; invoke the CLI with `python src/cli.py "your query"`.
Nodes return partial state dictionaries without mutation, tests should use
explicit module imports when package initializers re-export functions, and no
`.env` or secrets should be changed.
