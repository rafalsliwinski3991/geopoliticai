# geopoliticai

An English-language geopolitical research agent built on LangGraph.

## What it is

The expert pipeline is a two-node graph:

```text
START -> search_and_fetch -> answer -> END
```

`search_and_fetch` runs three batched Brave queries restricted to a curated set
of domains, fetches up to ten of those pages, and extracts article text with
trafilatura. `answer` sends the retrieved text to one streamed plain-text OpenAI
call. Search, extraction, and model failures are surfaced to the client; there
is no degraded or fabricated answer.

The maintained application lives under `app/`. `app/README.md` documents setup,
the API contract, and the static English frontend; `app/src/` is the Python
import root. The FastAPI app exposes `GET /api/health`,
`POST /api/run_pipeline/stream`, and `/` for the frontend, with no synchronous
pipeline route.
