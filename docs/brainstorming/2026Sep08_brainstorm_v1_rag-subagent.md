# A new subagent built on the RAG pattern: a second retrieval substrate alongside the expert's live web search

**Started:** 2026-09-08
**Status:** In progress
**Mode:** batch (similar questions per round, default)

## Target design

*(Not yet stateable — Q1 decides the corpus, which decides everything else.)*

## Context verified

Facts established from the repo and from Context7, not from the user.

### The app already implements RAG

- `app/src/agents/expert/` is a two-node retrieve-then-generate pipeline:
  `START -> search_and_fetch -> answer -> END` (`agents/expert/graph.py`).
- Retrieval is live Brave web search restricted to a 28-domain editorial allow-list
  (`agents/expert/consts/sources.py`), three batched queries, followed by concurrent
  fetch + trafilatura extraction (`search.py:search_allowlisted`, `search.py:fetch_sources`).
- Augmentation is literal prompt stuffing: `agents/expert/nodes/answer.py:_sources_block`
  renders `--- SOURCE ---\nTitle/URL/text` blocks into one human prompt.
- Sizing: `RETRIEVAL = RetrievalSettings(fetch_candidates=10, keep_sources=8)`
  (`agents/expert/config.py`); `max_source_chars=20_000`, `min_source_chars=500`,
  `max_per_domain=2` (`agents/expert/consts/sources.py`).
- **There is no ranking, no chunking, no embedding, and no similarity step anywhere.**
  Relevance comes entirely from Brave's ordering plus `merge_candidates`' round-robin
  interleave and paywall deferral (`search.py:merge_candidates`).

### No vector infrastructure exists today

- `app/pyproject.toml` dependencies contain no embeddings, no vector store, no SQLAlchemy,
  no numpy. The full list: fastapi, langchain-core, langchain-openai, langgraph,
  langgraph-checkpoint-postgres, psycopg[binary], openai, pydantic, python-dotenv, httpx,
  trafilatura, uvicorn, arize-phoenix-otel, openinference-instrumentation-langchain.
- Postgres is `postgres:16-alpine` (`docker-compose.yml:3`) — **the stock image, no
  pgvector extension**. Using pgvector means swapping the image (e.g. `pgvector/pgvector:pg16`).
- Postgres is used for exactly one thing: the LangGraph checkpointer
  (`AsyncPostgresSaver` over a raw `psycopg_pool.AsyncConnectionPool`, `api.py`). There is
  no ORM, no migration tool, and no application table.

### Context7 — `langchain-postgres` (`/langchain-ai/langchain-postgres`, verified 2026-09-08)

- Current vector store is `PGVectorStore`, created async:
  `await PGVectorStore.create(engine=pg_engine, table_name=..., embedding_service=..., metadata_columns=[...])`.
- Its connection object is a `PGEngine`, built from a **SQLAlchemy async engine**:
  `PGEngine.from_connection_string(url="postgresql+psycopg://...")` or `PGEngine.from_engine(...)`.
  **This pulls in SQLAlchemy**, which the app does not currently have, and is a second,
  parallel connection pool alongside the checkpointer's raw psycopg pool.
- The package is psycopg3-only (`postgresql+psycopg://`, not `psycopg2`), which is compatible
  with the app's pinned `psycopg[binary]>=3.2,<4.0`.
- Async API: `aadd_documents(documents=[Document(id=..., page_content=..., metadata=...)])`,
  `asimilarity_search(query, filter={"content": {"$gte": 1}})` with `$`-operator metadata filters.

### In-flight work this collides with

- `app/src/agents/reporter/` exists on `main`/HEAD as **empty `consts/` and `nodes/` directories
  with no files** — scaffolding, untracked by git (`git ls-files app/src/agents/reporter` is empty).
- `docs/plans/2026Sep04_plan_reporter-agent_v3.md` is a full-tier plan, planned against `31583ef`.
- Per that plan's §0, two unmerged branches already carry implementations:
  `2026Sep05-reporter-agent` (11 commits, complete but v1-level) and
  `2026Sep06-reporter-agent-codex` (5 commits, Commits 1-3 only).
- The reporter adds a **third** classifier destination (`report`) to
  `Destination = Literal["geopolitical", "other"]` in `agents/orchestrator/state.py`.
  A new RAG agent routed by the classifier would be the **fourth**.

### The agent-boundary pattern a new agent must follow

- A subagent is a separately compiled graph **invoked inside an orchestrator node**, never
  passed to `add_node`, because the state schemas share no key
  (`agents/orchestrator/nodes/expert.py`, and CLAUDE.md states this as a rule).
- No `config` is passed to the child `ainvoke`; LangGraph propagates the parent run through
  contextvars, which is what produces the `expert:<task id>` stream namespace.
- Shared modules (`config.py`, `models.py`, `search.py`, `llm.py`, `tracing.py`, `api.py`)
  never import agents. Errors are `PipelineError` subclasses carrying a `status` ClassVar
  (503 search, 422 no sources, 502 LLM).

## Settled decisions

*(none yet)*

## Design tree

- **Q1 — What corpus does this retrieve from?** OPEN *(root; everything hangs off it)*
- **Q3 — Sequencing against the unmerged reporter work** OPEN *(independent of Q1)*
- Downstream of Q1, not yet askable:
  - Q2 — How the user reaches this agent (classifier destination vs explicit trigger vs upload flow)
  - Chunking / embedding model / dimension
  - Vector store choice and where it lives
  - Ingestion trigger: build-time, on-upload, or background
  - Whether retrieval is vector-only or hybrid with the existing Brave path
  - Citation format and whether it must match the expert's `[anchor](URL)`
  - Failure policy (CLAUDE.md forbids degraded fallbacks in the expert; does that carry?)
  - Testing without a database / without network

## Current frontier (open questions)

- **Q1 — What corpus does this retrieve from?** *(next up)*
- **Q3 — Sequencing against the unmerged reporter work** *(asked in the same round)*

## Carried as flags, not decisions

*(none yet)*

## Round log
