# Simplification & Refactor Plan v1 — 2026-08-25

**Derived from:** `docs/brainstorming/2026Aug25_brainstorm_v1.md` (18 rounds, all settled).

**Verified against:** the working tree on branch `2026Aug26-setup-klaussy`; `app/uv.lock`
(`langgraph>=1.0.0`, `langchain-core 0.3.x`, `langchain-openai 0.3.x`, `httpx 0.27+`);
`.github/workflows/unit-tests.yml`; `frontend/index.html`.

**Scope:** one decisive in-place rewrite on a branch (Q14). `main` keeps working because the
work never lands there until the branch is green.

---

## Summary

The pipeline collapses from 15 nodes / 6-14 LLM calls / ~15-20 Brave requests to **2 nodes,
1 LLM call, 3 Brave requests, 10 page fetches**.

```text
Before: START -> ingest_request -> build_research_plan
          -> search_{left,center,right,people}_pool -> {4 analysts}
          -> referee -> (blocked -> referee_blocked_summary | cross_check_facts
          -> compose_final) -> supervisor -> END

After:  START -> search_and_fetch -> answer -> END
```

| | Before | After |
| --- | --- | --- |
| `app/src` LOC | 3,056 | ~700 |
| Graph nodes | 15 | 2 |
| LLM calls / run | 6-14 | 1 |
| Brave requests / run | ~15-20 | 3 |
| Page fetches / run | 0 | 10 |
| `PipelineState` keys | 17 | 3 |
| Python deps | 10 | 11 (`+trafilatura`) |
| Languages | English + Polish | English only |

Three cross-cutting rules govern every step below:

1. **No deterministic fallbacks anywhere** (Q5). The model's markdown is the product. Nothing
   post-processes it, prefixes it, badges it, or reshapes it.
2. **Hard-fail, never degrade** (Q6). Zero allow-listed results, all fetches failing, or an LLM
   error each reach the client as an error. A source whose fetch fails is *dropped*, not
   downgraded to its Brave snippet.
3. **The allow-list is a retrieval constraint only** (Q2, Q8). The left/centre/right labels never
   appear in the graph, the state, the prompt, or the output.

---

## Module fate

| Path | Fate |
| --- | --- |
| `app/src/nodes/**` (14 files, 1,499 LOC) | **delete** |
| `app/src/planning.py` | **delete** |
| `app/src/render.py` | **delete** |
| `app/src/graph.py` | rewrite (155 -> ~90 LOC) |
| `app/src/models.py` | rewrite (192 -> ~60 LOC) |
| `app/src/search.py` | rewrite (280 -> ~200 LOC) — becomes node 1 |
| `app/src/llm.py` | rewrite (140 -> ~50 LOC) |
| `app/src/config.py` | rewrite (217 -> ~150 LOC) |
| `app/src/answer.py` | **new** — node 2 |
| `app/src/api.py` | edit |
| `app/src/cli.py` | edit |
| `app/src/database.py` | **untouched** (Q15) |
| `frontend/index.html` | edit |
| `app/pyproject.toml`, `app/uv.lock` | edit + relock |
| `app/tests/**` | 4 files survive/adapt, 5 delete, 4 new |
| root `main.py`, `Dockerfile`, `requirements.txt` | fix **after** the refactor (Q16) |
| `AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md` | edit (project rule) |
| `ai_tools_tables.md` | **untouched** — no skill/hook/agent config changes |

> **One deliberate addition beyond the brainstorm's module list:** `app/src/answer.py`. Q14
> enumerated rewrites for `graph.py`/`models.py`/`llm.py`/`search.py` but the second node needs a
> home. It does not go in `llm.py`, which is the OpenAI boundary per the project rules, nor in
> `graph.py`, which stays pure wiring. `search.py` = node 1, `answer.py` = node 2.

---

## Step 0 — Branch and dependency

```bash
git checkout -b 2026Aug25-two-node-rewrite
```

`app/pyproject.toml`:

```diff
 dependencies = [
     "fastapi>=0.110,<1.0",
     "langchain-core>=0.3,<1.0",
     "langchain-openai>=0.3,<1.0",
     "langgraph>=1.0.0",
     "openai>=1.40,<2.0",
     "pydantic>=2.0,<3.0",
     "python-dotenv>=1.0.1",
     "asyncpg>=0.29,<1.0",
     "httpx>=0.27,<1.0",
+    "trafilatura>=2.0,<3.0",
     "uvicorn[standard]>=0.29,<1.0",
 ]
```

```diff
 [tool.setuptools]
 package-dir = {"" = "src"}
 py-modules = [
     "api",
+    "answer",
     "cli",
     "config",
     "graph",
     "llm",
     "models",
-    "planning",
-    "render",
     "search",
 ]

-[tool.setuptools.packages.find]
-where = ["src"]
-include = ["nodes*"]
-
```

CI runs `uv sync --locked`, so the lockfile must be regenerated in the same commit:

```bash
cd app && uv lock && uv sync --locked --dev
```

`trafilatura` ships no type stubs and `make lint` runs `mypy --strict`. Use the same escape hatch
`database.py` already uses for `asyncpg` — `import trafilatura  # type: ignore[import-untyped]` —
rather than a new mypy config block.

---

## Step 1 — `app/src/config.py`

Deletes `ENGLISH_INFOSPHERE_SOURCES`, `POLISH_INFOSPHERE_SOURCES`, `get_infosphere_sources`,
`AGENT_MODEL_NAMES`, `get_analyst_additional_sources`, and `DEFAULT_ANALYST_ADDITIONAL_SOURCES`.
Adds the flat allow-list, the search batches, and the retrieval budget constants.

Replace the top of the module (everything from `ENGLISH_INFOSPHERE_SOURCES` through
`AGENT_MODEL_NAMES`) with:

```python
# --- Retrieval allow-list -------------------------------------------------
#
# One flat English-language list. The lean grouping in the comments is a
# curation guide for *choosing* entries; it never reaches the graph, the state,
# the prompt, or the output (Q2, Q8).
ALLOWED_DOMAINS: tuple[str, ...] = (
    # wires and reporting
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "npr.org",
    "aljazeera.com",
    "dw.com",
    "france24.com",
    "axios.com",
    "politico.com",
    "csmonitor.com",
    "bloomberg.com",
    "ft.com",
    "nytimes.com",
    "washingtonpost.com",
    "theguardian.com",
    "wsj.com",
    "economist.com",
    # left-leaning commentary
    "vox.com",
    "thenation.com",
    "motherjones.com",
    # right-leaning commentary
    "nationalreview.com",
    "thedispatch.com",
    "washingtonexaminer.com",
    "reason.com",
    "foxnews.com",
    # think tanks, spread across the spectrum
    "brookings.edu",
    "aei.org",
    "hoover.org",
)

# Three concurrent Brave queries (Q17). Each batch is deliberately mixed across
# the spectrum: if batch A were all left-leaning, a topic covered only by batch A
# would produce a one-sided answer with nothing downstream to notice.
SEARCH_BATCHES: tuple[tuple[str, ...], ...] = (
    (
        "reuters.com",
        "bbc.com",
        "theguardian.com",
        "wsj.com",
        "npr.org",
        "nationalreview.com",
        "politico.com",
        "aljazeera.com",
        "brookings.edu",
        "vox.com",
    ),
    (
        "apnews.com",
        "bloomberg.com",
        "ft.com",
        "washingtonpost.com",
        "foxnews.com",
        "dw.com",
        "axios.com",
        "aei.org",
        "thenation.com",
    ),
    (
        "economist.com",
        "nytimes.com",
        "thedispatch.com",
        "csmonitor.com",
        "france24.com",
        "washingtonexaminer.com",
        "reason.com",
        "hoover.org",
        "motherjones.com",
    ),
)

# Fetch-ordering hint only. These outlets usually return a stub that trafilatura
# rejects, so they are tried last rather than consuming fetch slots. They are NOT
# excluded: a free article from one of them is as good as any other.
HARD_PAYWALLED_DOMAINS: frozenset[str] = frozenset(
    {
        "wsj.com",
        "ft.com",
        "economist.com",
        "nytimes.com",
        "washingtonpost.com",
        "bloomberg.com",
    }
)

# --- Retrieval budget (Q10) ----------------------------------------------
BRAVE_RESULTS_PER_QUERY = 10
FETCH_CANDIDATES = 10
KEEP_SOURCES = 8
MAX_PER_DOMAIN = 2
FETCH_TIMEOUT_SECONDS = 5.0
MIN_SOURCE_CHARS = 500
MAX_SOURCE_CHARS = 20_000

# Brave documents a ~400 character / ~50 word ceiling on `q`. A 10-domain site
# filter costs ~198 chars and 19 words, and the API accepts queries up to 2,000
# chars, so the user's query must be trimmed before the filter is appended.
MAX_BRAVE_QUERY_CHARS = 140
MAX_BRAVE_QUERY_WORDS = 20

DEFAULT_MODEL = "gpt-4o-mini"  # Q9
DEFAULT_OPENAI_TIMEOUT_SECONDS = 60.0
DEFAULT_OPENAI_MAX_OUTPUT_TOKENS = 16_384
REQUIRED_ENV_VARS = ("OPENAI_API_KEY", "BRAVE_SEARCH_KEY")
```

`get_model` loses its per-agent branch:

```diff
-def get_model(agent_key: str | None = None) -> str:
-    """Return the configured OpenAI model, optionally overridden per agent key."""
+def get_model() -> str:
+    """Return the configured OpenAI model."""
     base_model = os.getenv("OPENAI_MODEL")
-    fallback = (
-        base_model.strip() if base_model and base_model.strip() else DEFAULT_MODEL
-    )
-    if not agent_key:
-        return fallback
-
-    return AGENT_MODEL_NAMES.get(agent_key.strip().lower(), fallback)
+    return base_model.strip() if base_model and base_model.strip() else DEFAULT_MODEL
```

`_get_env_var`, `get_openai_timeout_seconds`, `get_openai_max_output_tokens`, `init_environment`
and `require_env` are kept verbatim. `get_analyst_additional_sources` and
`DEFAULT_ANALYST_ADDITIONAL_SOURCES` are deleted.

---

## Step 2 — `app/src/models.py`

192 LOC -> ~60. Everything Polish, every claim/verdict/plan/referee type, the `ErrorRecord`
channel, and all four `operator.add` reducers go. Nothing writes concurrently any more (Q4), so
the reducers have no job.

Full replacement:

```python
"""Shared data structures for the pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class PipelineError(RuntimeError):
    """A failure the client must see, never a degraded answer (Q6)."""


class SearchUnavailableError(PipelineError):
    """Every Brave request attempted for this run failed."""


class NoSourcesError(PipelineError):
    """No allow-listed page survived search, fetch, and extraction."""


@dataclass(frozen=True)
class Candidate:
    """An allow-listed Brave result, before its page is fetched."""

    title: str
    url: str
    domain: str


@dataclass(frozen=True)
class Source:
    """An allow-listed page whose article text was fetched and extracted."""

    title: str
    url: str
    text: str


class PipelineState(TypedDict):
    """LangGraph state. Three keys, no reducers, no concurrent writers."""

    query: str
    sources: list[Source]
    answer: str


def build_initial_pipeline_state(query: str) -> PipelineState:
    """Return the initial state for one request."""
    normalized = " ".join((query or "").split())
    if not normalized:
        raise ValueError("Query must not be empty.")
    return {"query": normalized, "sources": [], "answer": ""}
```

Deleted from this module: `Source.id`/`notes`/`lane`/`credibility_tier`/`snippet`/
`content_excerpt`/`publisher`/`published_at`/`source_type`, `Claim`, `FactCheckResult`,
`ResearchPlan`, `RefereeReport`, `ErrorRecord`, `build_error_record`, `detect_language`,
`normalize_language`, `normalize_report_mode`, `_POLISH_DIACRITICS`, `_POLISH_STOPWORDS`.

---

## Step 3 — `app/src/search.py` (node 1, zero LLM calls)

Replaces the per-domain loop (`web_searcher`, ~130 LOC of loop + fallback) with three concurrent
batched OR queries, a merge, and a concurrent fetch/extract pass. The whole module is async; the
lane prefixes (`LANE_SOURCE_PREFIXES`, `_source_id_for_lane`, `_renumber_lane_sources`) and the
snippet path (`_normalize_source_notes`, `MAX_SOURCE_NOTES_CHARS`) are deleted — Q6 removed
snippets as an evidence path entirely.

Full replacement:

```python
"""Allow-listed search, page fetch, and article extraction (graph node 1)."""

from __future__ import annotations

import asyncio
import logging
import os
from collections import Counter
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

import httpx
import trafilatura  # type: ignore[import-untyped]

from config import (
    ALLOWED_DOMAINS,
    BRAVE_RESULTS_PER_QUERY,
    FETCH_CANDIDATES,
    FETCH_TIMEOUT_SECONDS,
    HARD_PAYWALLED_DOMAINS,
    KEEP_SOURCES,
    MAX_BRAVE_QUERY_CHARS,
    MAX_BRAVE_QUERY_WORDS,
    MAX_PER_DOMAIN,
    MAX_SOURCE_CHARS,
    MIN_SOURCE_CHARS,
    SEARCH_BATCHES,
)
from models import (
    Candidate,
    NoSourcesError,
    PipelineState,
    SearchUnavailableError,
    Source,
)

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_TIMEOUT_SECONDS = 10.0
BRAVE_MAX_QUERY_CHARS = 400
BRAVE_MAX_QUERY_WORDS = 50

FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def _normalize_domain(url: str) -> str:
    """Return the lowercase host of a URL-like string, without a `www.` prefix."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    host = (parsed.netloc or parsed.path.split("/")[0]).lower().strip()
    return host[4:] if host.startswith("www.") else host


def allowed_domain(url: str) -> str | None:
    """Return the allow-list entry this URL belongs to, or None if out of list."""
    host = _normalize_domain(url)
    if not host:
        return None
    for allowed in ALLOWED_DOMAINS:
        if host == allowed or host.endswith(f".{allowed}"):
            return allowed
    return None


def _trim_query(query: str) -> str:
    """Trim the user query to fit alongside a site filter in Brave's `q` budget."""
    words = query.split()[:MAX_BRAVE_QUERY_WORDS]
    while words and len(" ".join(words)) > MAX_BRAVE_QUERY_CHARS:
        words.pop()
    return " ".join(words)


def build_batch_query(query: str, domains: Sequence[str]) -> str:
    """Build one `<query> (site:a OR site:b ...)` string inside Brave's limits."""
    head = _trim_query(query)
    if not head:
        raise ValueError("Query is empty after trimming.")
    kept = list(domains)
    while kept:
        site_filter = " OR ".join(f"site:{domain}" for domain in kept)
        candidate = f"{head} ({site_filter})"
        within_budget = (
            len(candidate) <= BRAVE_MAX_QUERY_CHARS
            and len(candidate.split()) <= BRAVE_MAX_QUERY_WORDS
        )
        if within_budget:
            return candidate
        logger.warning("Brave query over budget; dropping domain=%s", kept[-1])
        kept.pop()
    raise ValueError("Query too long to combine with any site filter.")


async def _brave_batch(
    client: httpx.AsyncClient,
    query: str,
    domains: Sequence[str],
) -> list[Candidate]:
    """Run one batched Brave query and return its allow-listed results."""
    response = await client.get(
        BRAVE_SEARCH_URL,
        params={"q": build_batch_query(query, domains), "count": BRAVE_RESULTS_PER_QUERY},
        timeout=BRAVE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    web = payload.get("web", {}) if isinstance(payload, dict) else {}
    results = web.get("results", []) if isinstance(web, dict) else []

    candidates: list[Candidate] = []
    for item in results if isinstance(results, list) else []:
        url = (item.get("url") or "").strip()
        domain = allowed_domain(url)
        if domain is None:
            # Brave honours `site:` loosely; this is the hard gate.
            logger.debug("Dropped out-of-allowlist URL: %s", url)
            continue
        candidates.append(
            Candidate(
                title=(item.get("title") or "Untitled").strip(),
                url=url,
                domain=domain,
            )
        )
    return candidates


def merge_candidates(batches: Sequence[Sequence[Candidate]]) -> list[Candidate]:
    """Interleave the batches by rank, dedupe by URL, and cap results per domain."""
    merged: list[Candidate] = []
    seen_urls: set[str] = set()
    per_domain: Counter[str] = Counter()
    depth = max((len(batch) for batch in batches), default=0)
    for rank in range(depth):
        for batch in batches:
            if rank >= len(batch):
                continue
            candidate = batch[rank]
            if candidate.url in seen_urls:
                continue
            if per_domain[candidate.domain] >= MAX_PER_DOMAIN:
                continue
            seen_urls.add(candidate.url)
            per_domain[candidate.domain] += 1
            merged.append(candidate)
    # Stable sort: free-to-read first, interleave order preserved within groups.
    merged.sort(key=lambda item: item.domain in HARD_PAYWALLED_DOMAINS)
    return merged


async def _fetch_and_extract(
    client: httpx.AsyncClient,
    candidate: Candidate,
) -> Source | None:
    """Fetch one page and extract its article text; return None on any failure."""
    try:
        response = await client.get(candidate.url, timeout=FETCH_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.info("Fetch failed url=%s: %s", candidate.url, exc)
        return None

    if "html" not in response.headers.get("content-type", "").lower():
        logger.info("Skipped non-HTML url=%s", candidate.url)
        return None

    # trafilatura is CPU-bound and synchronous; keep it off the event loop.
    text = await asyncio.to_thread(
        trafilatura.extract,
        response.text,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text or len(text) < MIN_SOURCE_CHARS:
        # Paywall stubs and consent walls land here and are dropped (Q6, Q18).
        logger.info("Extraction empty or too short url=%s", candidate.url)
        return None

    return Source(
        title=candidate.title,
        url=candidate.url,
        text=text[:MAX_SOURCE_CHARS],
    )


async def search_and_fetch(state: PipelineState) -> dict[str, Any]:
    """Search the allow-list, fetch the top pages, and extract their article text."""
    brave_key = os.getenv("BRAVE_SEARCH_KEY")
    if not brave_key:
        raise SearchUnavailableError("Missing BRAVE_SEARCH_KEY for live search.")
    query = state["query"]

    search_headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": brave_key,
    }
    async with httpx.AsyncClient(headers=search_headers) as client:
        results = await asyncio.gather(
            *(_brave_batch(client, query, batch) for batch in SEARCH_BATCHES),
            return_exceptions=True,
        )

    batches: list[list[Candidate]] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.warning("Brave batch failed: %s", result)
            continue
        batches.append(result)
    if not batches:
        raise SearchUnavailableError("Every Brave request failed for this run.")

    candidates = merge_candidates(batches)[:FETCH_CANDIDATES]
    if not candidates:
        raise NoSourcesError(
            "No allow-listed sources were found for this query. Try rephrasing it."
        )

    async with httpx.AsyncClient(
        headers=FETCH_HEADERS, follow_redirects=True
    ) as client:
        fetched = await asyncio.gather(
            *(_fetch_and_extract(client, candidate) for candidate in candidates)
        )

    sources = [source for source in fetched if source is not None][:KEEP_SOURCES]
    if not sources:
        raise NoSourcesError(
            "Every allow-listed page for this query failed to fetch or extract."
        )

    logger.info(
        "search_and_fetch: %d candidates -> %d sources (%d chars)",
        len(candidates),
        len(sources),
        sum(len(source.text) for source in sources),
    )
    return {"sources": sources}
```

Three behaviours worth naming explicitly:

- **`allowed_domain` is the hard gate, not the `site:` operator.** Brave honours `site:` as a
  ranking hint; an out-of-list URL can and does come back. Every candidate is re-checked in
  Python before it can become a `Candidate`, and only a `Candidate` can become a `Source`.
- **Query trimming is not cosmetic.** `api.py` accepts queries up to 2,000 characters; a 10-domain
  site filter needs ~198 of Brave's ~400. Without `_trim_query` a long query silently truncates
  server-side and the filter is lost — the exact silent-truncation failure Q17 was chosen to avoid.
- **Partial Brave failure is survivable, total failure is not.** Two of three batches failing still
  produces an answer over a narrower slice; all three raises `SearchUnavailableError`.

---

## Step 4 — `app/src/llm.py`

140 LOC -> ~50. `StructuredOutputChain` and every `with_structured_output` path go with the
analysts. One streaming text chain remains.

Full replacement:

```python
"""OpenAI boundary: one streamed plain-text chain."""

from __future__ import annotations

from collections.abc import AsyncIterator

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from config import (
    get_model,
    get_openai_max_output_tokens,
    get_openai_timeout_seconds,
)

DEFAULT_MAX_RETRIES = 2


class LLMInvocationError(RuntimeError):
    """Raised when the model call fails or returns nothing usable."""


def _build_client() -> ChatOpenAI:
    """Return the single configured chat client used by the answer node."""
    return ChatOpenAI(
        model=get_model(),
        temperature=0.0,
        max_completion_tokens=get_openai_max_output_tokens(),
        timeout=get_openai_timeout_seconds(),
        max_retries=DEFAULT_MAX_RETRIES,
        streaming=True,
    )


async def astream_text(
    system_prompt: str,
    human_prompt: str,
    *,
    config: RunnableConfig | None = None,
) -> AsyncIterator[str]:
    """Stream plain-text chunks for one system/human prompt pair."""
    messages = [SystemMessage(system_prompt), HumanMessage(human_prompt)]
    try:
        async for chunk in _build_client().astream(messages, config=config):
            content = chunk.content
            if isinstance(content, str) and content:
                yield content
    except Exception as exc:  # noqa: BLE001 - single boundary, re-raised as ours
        raise LLMInvocationError("Model call failed.") from exc
```

**`ChatPromptTemplate` is deliberately gone.** The old chains passed article content through
`ChatPromptTemplate` with `{variable}` substitution. Source text now contains real article prose —
code blocks, JSON, LaTeX, `{` and `}` — and any brace in it would be read as a template variable
and raise `KeyError` mid-run. Messages are built directly from strings instead.

`streaming=True` plus an explicit `.astream()` is what makes `on_chat_model_stream` fire under
`astream_events`, which is how the SSE token path stays alive with only one LLM call left.

---

## Step 5 — `app/src/answer.py` (new, node 2, one LLM call)

```python
"""Answer composition (graph node 2)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig

from llm import LLMInvocationError, astream_text
from models import NoSourcesError, PipelineState, Source

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a geopolitical research analyst. Answer the user's \
question using only the source documents supplied in this message. Treat your own \
background knowledge as unavailable.

Rules:

1. Every sentence that states a fact must carry an inline markdown link to the \
source it came from, written as [short anchor text](URL). Copy the URL character \
for character from the SOURCE block that sentence came from. Never invent, \
shorten, guess, or reconstruct a URL.
2. Where the sources conflict, say so explicitly and attribute each position to \
the outlet that holds it. Do not average conflicting accounts into a single \
neutral statement. Where the sources agree, do not manufacture a disagreement.
3. If the sources do not answer the question, say plainly what they do and do not \
establish. Do not fill the gap from your own knowledge.
4. Write in English, in markdown. Choose whatever structure the question calls \
for. There is no required template, heading, preamble, or closing section."""


def _sources_block(sources: list[Source]) -> str:
    """Render fetched sources for the prompt: title, URL, and full article text."""
    return "\n\n".join(
        f"--- SOURCE ---\nTitle: {source.title}\nURL: {source.url}\n\n{source.text}"
        for source in sources
    )


async def answer(
    state: PipelineState,
    config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Write the finished answer from the fetched sources in one streamed call."""
    sources = state["sources"]
    if not sources:
        raise NoSourcesError("Answer node reached with no sources.")

    human_prompt = (
        f"Question: {state['query']}\n\n"
        f"Source documents:\n\n{_sources_block(sources)}"
    )
    logger.info(
        "answer: %d sources, prompt %d chars",
        len(sources),
        len(human_prompt),
    )

    chunks: list[str] = []
    async for chunk in astream_text(SYSTEM_PROMPT, human_prompt, config=config):
        chunks.append(chunk)
    text = "".join(chunks).strip()
    if not text:
        raise LLMInvocationError("Model returned an empty answer.")
    return {"answer": text}
```

Prompt shape follows Q11 and Q12 exactly: **no source IDs anywhere** — blocks are delimited by
`--- SOURCE ---` rather than numbered, so there is no ID for the model to cite and no round-trip to
resolve; and disagreement is required *conditionally* ("where the sources conflict"), because an
unconditional instruction invites a small model to manufacture conflict.

Worst-case prompt size: 8 sources x 20,000 chars = 160k chars ≈ 40k tokens, inside `gpt-4o-mini`'s
128k window. Typical runs land near 15k tokens.

---

## Step 6 — `app/src/graph.py`

155 LOC -> ~90. All 15 `add_node` calls, `_route_after_referee`, the conditional edge,
`normalize_report_mode`/`normalize_language` plumbing and `get_infosphere_sources` go. `configurable`
now carries only `thread_id`, so `nodes/runtime_config.py` dies with the package (Q4).

This module also becomes the **single shared implementation** behind both API endpoints (Q13).

Full replacement:

```python
"""Graph construction and execution for the GeopoliticAI workflow."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from answer import answer
from llm import LLMInvocationError
from models import PipelineState, build_initial_pipeline_state
from search import search_and_fetch

NODE_LABELS: dict[str, str] = {
    "search_and_fetch": "Searching and reading sources...",
    "answer": "Writing the answer...",
}

PipelineEvent = tuple[Literal["progress", "token"], str]


def build_graph() -> Any:
    """Construct and compile the two-node LangGraph pipeline."""
    graph = StateGraph(PipelineState)
    graph.add_node("search_and_fetch", search_and_fetch)
    graph.add_node("answer", answer)
    graph.add_edge(START, "search_and_fetch")
    graph.add_edge("search_and_fetch", "answer")
    graph.add_edge("answer", END)
    return graph.compile(name="GeopoliticAI")


graph = build_graph()


def build_runtime_config(*, thread_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Build LangGraph runtime configuration shared by both entrypoints."""
    configurable: dict[str, Any] = {}
    if thread_id is not None:
        if not thread_id.strip():
            raise ValueError("thread_id must not be empty when provided.")
        configurable["thread_id"] = thread_id
    return {"configurable": configurable}


def _chunk_text(chunk: object) -> str:
    """Extract text only from a streamed LangChain content chunk."""
    content = getattr(chunk, "content", chunk)
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


async def astream_pipeline(
    query: str,
    *,
    thread_id: str | None = None,
) -> AsyncIterator[PipelineEvent]:
    """Run one request, yielding ("progress", node) and ("token", text) events.

    Raises PipelineError or LLMInvocationError. It never yields a degraded or
    fabricated answer (Q6).
    """
    state = build_initial_pipeline_state(query)
    config = build_runtime_config(thread_id=thread_id)
    seen_nodes: set[str] = set()

    async for event in graph.astream_events(state, config=config, version="v2"):
        event_type = event.get("event", "")
        node = event.get("metadata", {}).get("langgraph_node", "")
        if (
            event_type == "on_chain_start"
            and node in NODE_LABELS
            and node not in seen_nodes
        ):
            seen_nodes.add(node)
            yield ("progress", node)
        elif event_type == "on_chat_model_stream" and node == "answer":
            text = _chunk_text(event.get("data", {}).get("chunk"))
            if text:
                yield ("token", text)


async def run_pipeline(query: str, *, thread_id: str | None = None) -> str:
    """Run one request and return the finished answer.

    The synchronous path is the streaming path joined, so the two endpoints
    cannot drift (Q13).
    """
    parts: list[str] = []
    async for kind, text in astream_pipeline(query, thread_id=thread_id):
        if kind == "token":
            parts.append(text)
    result = "".join(parts).strip()
    if not result:
        raise LLMInvocationError("Pipeline produced no answer text.")
    return result
```

`invoke_pipeline(compiled_graph, ...)` is gone. Nothing calls the graph synchronously any more:
both nodes are `async def`, so `graph.invoke()` would fail, and the API is already async.

---

## Step 7 — `app/src/api.py`

Both endpoints stay; both now run through `astream_pipeline` / `run_pipeline` (Q13). `infosphere`
leaves the request model, `report_mode` dies with `supervisor`, the 30-entry bilingual label maps
collapse into `NODE_LABELS`, and errors become real errors instead of degraded 200s.

### 7.1 Imports and request model

```diff
 import database
 from config import init_environment, require_env
-from graph import (
-    build_runtime_config,
-    invoke_pipeline,
-)
-from graph import (
-    graph as pipeline_graph,
-)
-from models import build_initial_pipeline_state, normalize_language
+from graph import NODE_LABELS, astream_pipeline, run_pipeline
+from llm import LLMInvocationError
+from models import NoSourcesError, PipelineError, SearchUnavailableError
```

```diff
 class RunPipelineRequest(BaseModel):
     """Request payload for running the analysis pipeline."""

     query: str = Field(
         ...,
         min_length=1,
         max_length=MAX_QUERY_LENGTH,
         description="Query to analyze",
     )
-    infosphere: Literal["english", "polish"] = Field(
-        "polish", description="Which infosphere sources to use: english or polish"
-    )
```

`Literal` and `run_in_threadpool` drop out of the imports with it.

### 7.2 Error mapping

New helpers, replacing the two bilingual message constants:

```python
_ERROR_STATUS: tuple[tuple[type[Exception], int], ...] = (
    (NoSourcesError, 422),
    (SearchUnavailableError, 503),
    (LLMInvocationError, 502),
)


def _status_for(exc: Exception) -> int:
    """Map a known pipeline failure onto an HTTP status code."""
    for error_type, status in _ERROR_STATUS:
        if isinstance(exc, error_type):
            return status
    return 500


def _sse(payload: dict[str, str]) -> str:
    """Serialize one SSE data frame."""
    return f"data: {json.dumps(payload)}\n\n"
```

The messages carried in `NoSourcesError` / `SearchUnavailableError` are authored strings from
`search.py`, safe to show a user. `LLMInvocationError`'s message is the fixed string
`"Model call failed."`; the provider's exception stays in `__cause__` and reaches the log only.

Delete `_NODE_LABELS_PL` and `_NODE_LABELS_EN` (30 entries) entirely.

### 7.3 Streaming endpoint

```python
@router.post("/run_pipeline/stream")
async def run_pipeline_stream_endpoint(
    payload: RunPipelineRequest,
    request: Request,
) -> StreamingResponse:
    """Run the pipeline and stream progress and answer tokens over SSE."""
    _enforce_rate_limit(request)
    client_id = _resolve_client_id(request)
    log_id = await database.log_prompt(payload.query, client_id)

    async def _generate() -> AsyncGenerator[str, None]:
        parts: list[str] = []
        try:
            async for kind, value in astream_pipeline(payload.query):
                if kind == "progress":
                    yield _sse(
                        {"type": "progress", "node": value, "label": NODE_LABELS[value]}
                    )
                else:
                    parts.append(value)
                    yield _sse({"type": "token", "content": value})

            output = "".join(parts).strip()
            if not output:
                yield _sse(
                    {"type": "error", "message": "The model returned an empty answer."}
                )
                return
            yield _sse({"type": "result", "output": _sanitize_output(output)})
            if log_id is not None:
                await database.log_output(log_id, output)

        except (PipelineError, LLMInvocationError) as exc:
            logger.warning("Streaming pipeline failed: %s", exc)
            yield _sse({"type": "error", "message": str(exc)})
        except Exception:
            logger.exception("Streaming pipeline failed unexpectedly.")
            yield _sse(
                {
                    "type": "error",
                    "message": "An unexpected error occurred. Please try again.",
                }
            )

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

The SSE event vocabulary is unchanged — `progress` / `token` / `result` / `error` — so the frontend
contract survives. What changes is that a failed run now emits `error` instead of a `result`
carrying canned degraded prose.

### 7.4 Synchronous endpoint

```diff
     log_id = await database.log_prompt(payload.query, client_id)
     try:
-        output = await run_in_threadpool(
-            invoke_pipeline, pipeline_graph, payload.query, payload.infosphere
-        )
+        output = await run_pipeline(payload.query)
+    except (PipelineError, LLMInvocationError) as exc:
+        logger.warning("Pipeline failed: %s", exc)
+        raise HTTPException(status_code=_status_for(exc), detail=str(exc)) from None
     except Exception:
         logger.exception("Pipeline failed unexpectedly.")
         raise HTTPException(status_code=500, detail="Internal server error.") from None
```

Unchanged in this file: CORS, rate limiting, `_sanitize_output`, `_resolve_client_id`, the
`lifespan` hook, static-frontend mounting, and `/api/health`.

---

## Step 8 — `app/src/cli.py`

```diff
 import argparse
+import asyncio
 import sys

 from config import init_environment, require_env
 from graph import run_pipeline
-from models import detect_language


 def main() -> None:
     """Parse CLI arguments and run the pipeline."""
     parser = argparse.ArgumentParser(description="Run GeopoliticAI POC pipeline.")
     parser.add_argument("query", help="Query to analyze")
-    parser.add_argument(
-        "--infosphere",
-        choices=("english", "polish"),
-        default=None,
-        help=(
-            "Force a specific infosphere. "
-            "Defaults to auto-detecting from query language."
-        ),
-    )
-    parser.add_argument(
-        "--report",
-        choices=("compact", "full"),
-        default="compact",
-        help="Output mode: compact summary or full report.",
-    )
     parser.add_argument(
         "--log-level",
         choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
         default=None,
         help="Override logging level for this run.",
     )
     args = parser.parse_args()

     init_environment(log_level=args.log_level)
     require_env()

-    infosphere = args.infosphere or detect_language(args.query)
-    output = run_pipeline(
-        args.query,
-        infosphere=infosphere,
-        report_mode=args.report,
-    )
+    output = asyncio.run(run_pipeline(args.query))
     data = str(output).encode("utf-8", errors="replace")
```

New invocation: `cd app && python src/cli.py "your query"`. The documented
`--infosphere polish --report full` form is gone and every doc that shows it must change (Step 13).

---

## Step 9 — `frontend/index.html`

Three edits. The SSE handling loop (`progress` / `token` / `result` / `error`) needs no change.

**9.1 — remove the flag picker** (`index.html:339-355`):

```diff
-          <div class="lang-picker">
-            <button
-              class="lang-btn"
-              :class="{ active: infosphere === 'polish' }"
-              @click="infosphere = 'polish'"
-              title="Polski"
-              :disabled="isLoading"
-            >🇵🇱</button>
-            <button
-              class="lang-btn"
-              :class="{ active: infosphere === 'english' }"
-              @click="infosphere = 'english'"
-              title="English"
-              :disabled="isLoading"
-            >🇺🇸</button>
-          </div>
```

**9.2 — unconditional English subtitle** (`index.html:333-336`):

```diff
-              <p x-text="infosphere === 'polish'
-                ? 'Wieloperspektywiczna analiza geopolityczna z weryfikacją faktów.'
-                : 'Multi-perspective geopolitical analysis with fact verification.'">
-              </p>
+              <p>Geopolitical analysis grounded in cross-spectrum reporting.</p>
```

The old subtitle promised fact verification, which no longer exists in the pipeline.

**9.3 — collapse the `I18N` map and drop `infosphere` from the component**:

```diff
-      const I18N = {
-        polish: { ... },
-        english: { ... },
-      };
+      const I18N = {
+        welcome: "...",
+        timeout_error: "...",
+        connection_error: (msg) => `Connection error: ${msg}`,
+        server_error: (code) => `Server error (${code}).`,
+        time_locale: "en-US",
+      };
```

```diff
           input: "",
           isLoading: false,
-          infosphere: "polish",
           progressLog: [],

           init() {
-            this.messages = [{ role: "bot", text: I18N.polish.welcome, timestamp: new Date() }];
-            this.$watch("infosphere", (lang) => {
-              if (this.messages.length === 1 && this.messages[0].role === "bot") {
-                this.messages[0].text = I18N[lang].welcome;
-              }
-            });
+            this.messages = [{ role: "bot", text: I18N.welcome, timestamp: new Date() }];
             this.$nextTick(() => this.$refs.input?.focus());
           },

           t(key) {
-            return I18N[this.infosphere][key];
+            return I18N[key];
           },
```

```diff
-                body: JSON.stringify({ query: text, infosphere: this.infosphere }),
+                body: JSON.stringify({ query: text }),
```

Also drop the now-unused `.lang-picker` / `.lang-btn` CSS rules and any Polish example-query
strings in the welcome block.

---

## Step 10 — Deletions

```bash
cd app
git rm -r src/nodes
git rm src/planning.py src/render.py
git rm tests/unit_tests/test_cleanup_pipeline.py \
       tests/unit_tests/test_compose_final_inference.py \
       tests/unit_tests/test_llm_json_parsing.py \
       tests/unit_tests/test_configuration.py
```

That is 1,499 LOC of `src/nodes/**` plus 37 LOC of `planning.py` + `render.py`, and 312 LOC of
tests that assert the removed design (TRUE-only funnel, referee routing, structured-output JSON
repair, lane search pools).

Sanity check that nothing still imports the deleted modules:

```bash
grep -rn "from nodes\|import nodes\|from planning\|from render\|infosphere\|report_mode\|referee\|fact_check\|Claim\b" app/src app/tests
```

Expected result after the rewrite: no matches.

---

## Step 11 — Tests

Target: three things, per Q14. (1) Can an out-of-allowlist URL ever reach the prompt? (2) Do all
three hard-fail paths actually fail hard? (3) Does the API contract hold on both endpoints,
including streaming events and error shapes.

| File | Fate |
| --- | --- |
| `tests/unit_tests/test_database.py` (148) | survives verbatim |
| `tests/unit_tests/test_config_env.py` (105) | drop the `ANALYST_ADDITIONAL_SOURCES` parametrize case; the other two survive |
| `tests/unit_tests/test_search_enforcement.py` (135) | rewritten -> `test_search.py` |
| `tests/unit_tests/test_api.py` (243) | rewritten against the new contract |
| `tests/unit_tests/test_fetch.py` | new |
| `tests/unit_tests/test_answer.py` | new |
| `tests/unit_tests/test_config_allowlist.py` | new |
| `tests/integration_tests/test_graph.py` (17) | rewritten |

### 11.1 `tests/unit_tests/test_config_allowlist.py` (new)

Cheap invariants that catch the most likely hand-edit mistakes in a 28-entry list:

```python
from config import ALLOWED_DOMAINS, HARD_PAYWALLED_DOMAINS, SEARCH_BATCHES


def test_batches_partition_the_allowlist() -> None:
    batched = [domain for batch in SEARCH_BATCHES for domain in batch]
    assert sorted(batched) == sorted(ALLOWED_DOMAINS)
    assert len(batched) == len(set(batched)), "a domain appears in two batches"


def test_paywalled_set_is_a_subset_of_the_allowlist() -> None:
    assert HARD_PAYWALLED_DOMAINS <= set(ALLOWED_DOMAINS)


def test_domains_are_bare_hosts() -> None:
    for domain in ALLOWED_DOMAINS:
        assert "://" not in domain and "/" not in domain
        assert not domain.startswith("www.")
```

### 11.2 `tests/unit_tests/test_search.py` (new, replaces `test_search_enforcement.py`)

```python
import httpx
import pytest

import search
from models import Candidate, NoSourcesError, SearchUnavailableError


def _brave_response(results: list[dict]) -> httpx.Response:
    request = httpx.Request("GET", search.BRAVE_SEARCH_URL)
    return httpx.Response(200, json={"web": {"results": results}}, request=request)


@pytest.fixture(autouse=True)
def _set_brave_key(monkeypatch):
    monkeypatch.setenv("BRAVE_SEARCH_KEY", "test-key")


def test_allowed_domain_accepts_subdomains_and_rejects_lookalikes() -> None:
    assert search.allowed_domain("https://www.bbc.com/news/x") == "bbc.com"
    assert search.allowed_domain("https://edition.bbc.com/x") == "bbc.com"
    assert search.allowed_domain("https://bbc.com.evil.example/x") is None
    assert search.allowed_domain("https://en.wikipedia.org/wiki/X") is None


def test_batch_query_stays_inside_brave_limits() -> None:
    long_query = "word " * 400
    built = search.build_batch_query(long_query, search.SEARCH_BATCHES[0])
    assert len(built) <= search.BRAVE_MAX_QUERY_CHARS
    assert len(built.split()) <= search.BRAVE_MAX_QUERY_WORDS
    assert "site:reuters.com" in built


def test_batch_query_drops_domains_before_exceeding_the_budget() -> None:
    # 28 domains cannot fit; the builder must shed the tail, not truncate silently.
    built = search.build_batch_query("ukraine ceasefire", search.ALLOWED_DOMAINS)
    assert len(built) <= search.BRAVE_MAX_QUERY_CHARS
    assert "site:reuters.com" in built  # the head is kept


@pytest.mark.anyio
async def test_out_of_allowlist_urls_never_become_candidates(monkeypatch) -> None:
    response = _brave_response(
        [
            {"title": "Wikipedia", "url": "https://en.wikipedia.org/wiki/X",
             "description": "out of scope"},
            {"title": "Reuters report", "url": "https://www.reuters.com/world/x",
             "description": "allowed"},
        ]
    )

    async def fake_get(self, url, *, params=None, timeout=None):
        return response

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with httpx.AsyncClient() as client:
        candidates = await search._brave_batch(client, "x", ("reuters.com",))

    assert [c.url for c in candidates] == ["https://www.reuters.com/world/x"]


def test_merge_caps_results_per_domain_and_defers_paywalls() -> None:
    batch = [
        Candidate("a", "https://reuters.com/1", "reuters.com"),
        Candidate("b", "https://reuters.com/2", "reuters.com"),
        Candidate("c", "https://reuters.com/3", "reuters.com"),
    ]
    paywalled = [Candidate("d", "https://ft.com/1", "ft.com")]
    merged = search.merge_candidates([batch, paywalled])

    assert [c.url for c in merged] == [
        "https://reuters.com/1",
        "https://reuters.com/2",
        "https://ft.com/1",
    ]


@pytest.mark.anyio
async def test_zero_allowlisted_results_raises(monkeypatch) -> None:
    async def fake_get(self, url, *, params=None, timeout=None):
        return _brave_response([{"title": "X", "url": "https://example.com/x"}])

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises(NoSourcesError):
        await search.search_and_fetch({"query": "x", "sources": [], "answer": ""})


@pytest.mark.anyio
async def test_all_brave_requests_failing_raises(monkeypatch) -> None:
    async def fake_get(self, url, *, params=None, timeout=None):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    with pytest.raises(SearchUnavailableError):
        await search.search_and_fetch({"query": "x", "sources": [], "answer": ""})
```

> Note: `BRAVE_MAX_QUERY_CHARS`, `BRAVE_MAX_QUERY_WORDS`, `SEARCH_BATCHES`, `ALLOWED_DOMAINS` and
> `MAX_SOURCE_CHARS` are reached through the `search` module namespace in these tests — `search.py`
> imports them from `config`, so no second import is needed and a rename in `config.py` breaks the
> tests loudly rather than silently.

### 11.3 `tests/unit_tests/test_fetch.py` (new)

The hard-fail path Q6 cares most about, plus the paywall behaviour Q18 was chosen for:

```python
import httpx
import pytest

import search
from models import Candidate, NoSourcesError

_ARTICLE_HTML = "<html><body><article><p>" + ("Real reporting. " * 60) + "</p></article></body></html>"
_PAYWALL_HTML = "<html><body><div>Subscribe to continue reading.</div></body></html>"


def _html_response(body: str, status: int = 200) -> httpx.Response:
    request = httpx.Request("GET", "https://www.reuters.com/world/x")
    return httpx.Response(
        status, text=body, headers={"content-type": "text/html"}, request=request
    )


@pytest.mark.anyio
async def test_fetch_failure_drops_the_source_rather_than_degrading(monkeypatch) -> None:
    async def fake_get(self, url, *, timeout=None):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    candidate = Candidate("t", "https://www.reuters.com/world/x", "reuters.com")

    async with httpx.AsyncClient() as client:
        assert await search._fetch_and_extract(client, candidate) is None


@pytest.mark.anyio
async def test_paywall_stub_is_dropped(monkeypatch) -> None:
    async def fake_get(self, url, *, timeout=None):
        return _html_response(_PAYWALL_HTML)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    candidate = Candidate("t", "https://www.ft.com/x", "ft.com")

    async with httpx.AsyncClient() as client:
        assert await search._fetch_and_extract(client, candidate) is None


@pytest.mark.anyio
async def test_article_text_is_capped(monkeypatch) -> None:
    huge = "<html><body><article><p>" + ("x " * 40_000) + "</p></article></body></html>"

    async def fake_get(self, url, *, timeout=None):
        return _html_response(huge)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    candidate = Candidate("t", "https://www.reuters.com/world/x", "reuters.com")

    async with httpx.AsyncClient() as client:
        source = await search._fetch_and_extract(client, candidate)

    assert source is not None
    assert len(source.text) <= search.MAX_SOURCE_CHARS
```

Plus one end-to-end node test asserting that when every fetch fails, `search_and_fetch` raises
`NoSourcesError` rather than returning snippet-backed sources.

### 11.4 `tests/unit_tests/test_answer.py` (new)

```python
import pytest

import answer as answer_module
from models import NoSourcesError, Source


def test_sources_block_contains_no_numeric_ids() -> None:
    sources = [
        Source("Reuters report", "https://www.reuters.com/world/x", "body one"),
        Source("BBC report", "https://www.bbc.com/news/y", "body two"),
    ]
    block = answer_module._sources_block(sources)

    assert block.count("--- SOURCE ---") == 2
    assert "https://www.reuters.com/world/x" in block
    assert "SOURCE 1" not in block and "[1]" not in block


def test_source_text_with_braces_survives_prompt_assembly() -> None:
    # Regression guard: the old ChatPromptTemplate path raised KeyError here.
    sources = [Source("t", "https://www.bbc.com/news/y", 'config = {"a": {"b": 1}}')]
    block = answer_module._sources_block(sources)
    assert '{"a": {"b": 1}}' in block


@pytest.mark.anyio
async def test_answer_raises_without_sources() -> None:
    with pytest.raises(NoSourcesError):
        await answer_module.answer({"query": "x", "sources": [], "answer": ""})


@pytest.mark.anyio
async def test_answer_joins_streamed_chunks(monkeypatch) -> None:
    async def fake_stream(system_prompt, human_prompt, *, config=None):
        for chunk in ("Hello ", "world."):
            yield chunk

    monkeypatch.setattr(answer_module, "astream_text", fake_stream)
    state = {
        "query": "x",
        "sources": [Source("t", "https://www.bbc.com/news/y", "body")],
        "answer": "",
    }
    assert await answer_module.answer(state) == {"answer": "Hello world."}
```

### 11.5 `tests/unit_tests/test_api.py` (rewritten)

Keeps `test_health_check` and the prompt/output logging tests, updated to the new request body.
New assertions:

```python
def test_request_rejects_unknown_infosphere_field_gracefully(client) -> None:
    # `infosphere` is gone; pydantic ignores unknown fields by default, so the
    # request must still succeed rather than 422.
    ...


def test_sync_endpoint_maps_no_sources_to_422() -> None:
    async def boom(query, **kwargs):
        raise NoSourcesError("No allow-listed sources were found for this query.")

    with patch("api.run_pipeline", boom):
        response = TestClient(app).post("/api/run_pipeline", json={"query": "x"})

    assert response.status_code == 422
    assert "allow-listed" in response.json()["detail"]


def test_sync_endpoint_maps_search_unavailable_to_503() -> None: ...
def test_sync_endpoint_maps_llm_failure_to_502() -> None: ...


def test_stream_emits_progress_tokens_then_result() -> None:
    async def fake_stream(query, **kwargs):
        yield ("progress", "search_and_fetch")
        yield ("token", "Hello ")
        yield ("token", "world.")

    with patch("api.astream_pipeline", fake_stream):
        with patch("api.database.log_prompt", AsyncMock(return_value=None)):
            response = TestClient(app).post(
                "/api/run_pipeline/stream", json={"query": "x"}
            )

    events = _parse_sse(response.text)
    assert [e["type"] for e in events] == ["progress", "token", "token", "result"]
    assert events[0]["label"] == "Searching and reading sources..."
    assert events[-1]["output"] == "Hello world."


def test_stream_emits_error_event_and_no_result_on_failure() -> None:
    async def fake_stream(query, **kwargs):
        raise NoSourcesError("nothing usable")
        yield  # pragma: no cover - makes this an async generator

    with patch("api.astream_pipeline", fake_stream):
        with patch("api.database.log_prompt", AsyncMock(return_value=None)):
            response = TestClient(app).post(
                "/api/run_pipeline/stream", json={"query": "x"}
            )

    events = _parse_sse(response.text)
    assert [e["type"] for e in events] == ["error"]
    assert events[0]["message"] == "nothing usable"
```

Delete `test_stream_forwards_only_compose_final_tokens` and every other test naming a removed node.

### 11.6 `tests/integration_tests/test_graph.py` (rewritten)

```python
from graph import NODE_LABELS, build_graph


def test_graph_exposes_exactly_two_nodes() -> None:
    compiled = build_graph()
    nodes = set(compiled.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"search_and_fetch", "answer"}
    assert set(NODE_LABELS) == nodes


def test_graph_is_linear() -> None:
    edges = {(e.source, e.target) for e in build_graph().get_graph().edges}
    assert ("__start__", "search_and_fetch") in edges
    assert ("search_and_fetch", "answer") in edges
    assert ("answer", "__end__") in edges
```

`test_route_after_referee_blocks_invalid_or_blocked_reports` is deleted with the referee.

### 11.7 `tests/conftest.py`

Unchanged, but it now matters much more: nearly every new test is `@pytest.mark.anyio`, and the
`anyio_backend` fixture it provides is what makes those run.

---

## Step 12 — Documentation (project rule: all three together)

`CLAUDE.md`, `AGENTS.md`, and `.github/copilot-instructions.md` each need the same four edits:

1. **Workflow section** — replace the 15-node diagram with:

   ```text
   START -> search_and_fetch -> answer -> END
   ```

   and the surrounding prose: `PipelineState` is three keys with no reducers; `ResearchPlan`,
   `RefereeReport`, `Claim`, `FactCheckResult` are gone; search is constrained by one flat English
   allow-list in `config.py`; three batched Brave queries; pages are fetched and extracted with
   `trafilatura`; `configurable` carries only `thread_id`.

2. **Project layout** — `app/src/nodes/` no longer exists; `planning.py` and `render.py` are gone;
   `answer.py` is new.

3. **Commands** — the CLI example loses its flags:

   ```diff
   -cd app && python src/cli.py "your query" --infosphere polish --report full
   +cd app && python src/cli.py "your query"
   ```

4. **The false CI claim** (Q16 follow-up, flagged in the brainstorm as wrong *today*, independent
   of this refactor). `.github/workflows/unit-tests.yml` runs `uv sync --locked --dev` with
   `working-directory: app` and never touches the root `requirements.txt`:

   ```diff
   -CI still references the root `requirements.txt`, so account for that legacy
   -workflow before removing it.
   +CI does not reference the root `requirements.txt`: `.github/workflows/unit-tests.yml`
   +runs `uv sync --locked --dev` with `working-directory: app`, and compose builds
   +`./app` and `./frontend`. The root files are unused.
   ```

   The equivalent sentences are `CLAUDE.md:12-15`, `AGENTS.md:12-15`, and
   `.github/copilot-instructions.md:12`.

Also update the Working Rules bullets that reference removed concepts: `_route_after_referee`
(no conditional edges remain) and "Keep Polish and English prompts, sources, and progress labels
distinct" (there is one language now).

`ai_tools_tables.md` needs **no change** — no skill, hook, plugin, agent, or AI-tool config is
touched by this refactor.

---

## Step 13 — Root legacy files (post-refactor, Q16)

Do this **after** the branch is green, as a separate commit. All three files are currently broken:
`main.py` imports a nonexistent `geopoliticai` package, the root `Dockerfile` runs
`uvicorn geopoliticai.api:app`, and the root `requirements.txt` pins `langgraph>=0.2,<1.0` — which
*excludes* the `langgraph>=1.0.0` the app requires — plus an unused `tavily-python`.

`main.py`:

```python
"""Backward-compatible entrypoint for the GeopoliticAI CLI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "app" / "src"))

from cli import main  # noqa: E402

if __name__ == "__main__":
    main()
```

`requirements.txt` — regenerate from the maintained environment so it can never drift again:

```bash
cd app && uv export --no-dev --no-hashes --format requirements-txt > ../requirements.txt
```

`Dockerfile` — point at `app/` and the real module path:

```diff
-CMD ["uvicorn", "geopoliticai.api:app", "--host", "0.0.0.0", "--port", "8000"]
+WORKDIR /app/app/src
+CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

Then re-verify the three guidance docs still describe the root files accurately.

---

## Verification

Run in order; do not proceed past a red step.

```bash
cd app
uv lock && uv sync --locked --dev
make lint          # ruff + mypy --strict over src/ and tests/
make test          # unit tests
make integration_tests

# graph shape, live
langgraph dev      # confirm two nodes in Studio

# one real end-to-end run
python src/cli.py "What is the current state of the Ukraine ceasefire negotiations?"
```

Manual checks on that run's output, none of which a test can make:

- [ ] Every factual sentence carries an inline markdown link (Q11).
- [ ] **Click three or four of those links.** Q11 accepts hand-transcribed URLs, so broken links
      are the expected failure mode and nothing in the pipeline detects them.
- [ ] Cited outlets span more than one lean — if all eight sources are one publisher, `MAX_PER_DOMAIN`
      or the batch mix needs work.
- [ ] Where sources genuinely differ, the answer names the disagreement and attributes it; where
      they agree, it has not invented one (Q12).
- [ ] Attribution is correct: spot-check one claim against the article it links to (Q9 + Q10 risk).

Then the frontend and the failure paths:

```bash
cd .. && make up
```

- [ ] `POST /api/run_pipeline/stream` streams `progress` -> `token` -> `result`.
- [ ] With `BRAVE_SEARCH_KEY` unset, both endpoints return a visible error, not a canned answer.
- [ ] A deliberately obscure query (one with no allow-list coverage) produces a 422 / `error`
      event, not a fabricated answer.
- [ ] The Polish flag picker is gone and the UI is English throughout.
- [ ] With `DATABASE_URL` set, `prompt_logs` gains a row with both prompt and output.

Finally: `grep -rn "infosphere\|polish\|referee\|Claim\b" app/src frontend` returns nothing.

---

## Risks and open flags

Carried from the brainstorm, plus what this plan surfaced.

**Flagged in the brainstorm, still open:**

1. **Brave query limits are assumed, not verified.** `BRAVE_MAX_QUERY_CHARS = 400` /
   `BRAVE_MAX_QUERY_WORDS = 50` are the documented values as understood; confirm against current
   Brave docs before trusting `build_batch_query`'s budget arithmetic. The builder degrades safely
   (drops trailing domains with a warning) if the real limit is lower.
2. **Brave Goggles** would replace `site:` batching entirely and remove the query-length problem.
   Verify availability on the current plan; if available, `SEARCH_BATCHES` collapses to one query.
3. **Broken inline links** from hand-transcribed URLs (Q11) — undetectable in-pipeline by design.
4. **Wrong-source attribution** (Q9 + Q10): `gpt-4o-mini` over 8 long documents with no judge and
   no fallback. The prompt log (Q15) is the only place this can be caught, after the fact.
5. **Manufactured disagreement** (Q12) — mitigated only by the conditional wording of rule 2.

**Surfaced while writing this plan:**

6. **Six of the 28 domains are hard-paywalled** (`wsj`, `ft`, `economist`, `nytimes`,
   `washingtonpost`, `bloomberg`) and will usually be dropped by `trafilatura`. They stay in the
   list — a free article from them is as good as any — but `HARD_PAYWALLED_DOMAINS` defers them in
   fetch ordering so they do not consume the 10 fetch slots. **This is a recommendation, not a
   settled decision**; deleting the set changes only ordering. If the visible error rate is still
   too high after a week of real queries, widening the free-to-read half of the list is the lever.
7. **Query trimming for Brave.** The API accepts 2,000-character queries; Brave takes ~400 and the
   site filter needs ~200 of them. `_trim_query` keeps the first ~20 words / 140 chars. A long,
   conversational question therefore reaches Brave truncated — and Q7 removed the LLM planner that
   would otherwise compress it. This is the sharpest edge in the design: recall on verbose queries
   rests entirely on the first 20 words.
8. **`ChatPromptTemplate` removal is load-bearing**, not stylistic. Any future reintroduction of
   templated prompts around source text will raise `KeyError` on the first article containing a
   brace. `test_answer.py::test_source_text_with_braces_survives_prompt_assembly` guards it.
9. **The sync endpoint now buffers the whole stream in memory** before responding. At ~16k output
   tokens that is trivial, but it is a behaviour change from the old threadpool call.
10. **No checkpointer, still.** `thread_id` remains configuration context only; nothing resumes.
