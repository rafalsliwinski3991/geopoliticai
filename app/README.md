# GeopoliticAI Expert Agent

This application is a two-node LangGraph agent for English geopolitical
research. The graph is:

```text
START -> search_and_fetch -> answer -> END
```

`search_and_fetch` runs three batched Brave queries, fetches up to ten
allow-listed pages, and extracts article text with trafilatura. `answer` sends
the retrieved text to one streamed OpenAI plain-text call. Search, extraction,
and model failures are surfaced to clients; there is no degraded answer.

Agent-specific code lives under `src/agents/expert/`. Shared retrieval and LLM
boundaries are in `src/search.py` and `src/llm.py`. The API accepts `{query}`
only, and the static frontend is English-only.

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
are `OPENAI_API_KEY` and `BRAVE_SEARCH_KEY`; never commit the populated
file. Optional settings are documented in the repository guidance files.
Run checks with `make lint`, `make test`, and `make integration_tests`.
