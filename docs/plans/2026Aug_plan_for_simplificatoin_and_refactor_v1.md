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

