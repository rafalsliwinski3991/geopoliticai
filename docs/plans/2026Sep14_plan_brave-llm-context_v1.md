# Plan: Brave LLM Context retrieval

**Depth:** Standard
**Implements:** `docs/brainstorming/2026Sep14_brainstorm_v1_brave-llm-context.md`
**Run commands from:** `app/`

## 1. Scope and non-goals

**Behavior after the change.** The expert's `search_and_fetch` node makes exactly
one `GET https://api.search.brave.com/res/v1/llm/context` request per question,
restricted to the allow-list with an inline Goggle. Brave returns pre-extracted
snippets; no page is downloaded and nothing is extracted locally.

- `search_sources(query, policy)` (was `search_allowlisted`): one LLM Context call,
  allow-list gate, snippets joined into `Candidate.text`, dedupe / 2-per-domain cap /
  paywalled domains last.
- `filter_sources(candidates, policy)` (was `fetch_sources`): no I/O; drops
  candidates whose text is shorter than `min_source_chars`, trims to
  `max_source_chars`, returns `Source` objects. Becomes a plain synchronous function.
- Module moves from `src/search.py` to `src/utils/search.py`.

**Unchanged.**
- Node name `search_and_fetch`, graph shape, `RETRIEVAL.fetch_candidates=10`,
  `RETRIEVAL.keep_sources=8`, `Source` shape, `answer` node, API/SSE contract.
- Error types and statuses: missing key or failed request → `SearchUnavailableError`
  (503); nothing usable → `NoSourcesError` (422). No fallback.
- `allowed_domain` semantics (subdomains accepted, lookalikes rejected).
- Brave defaults for `maximum_number_of_tokens`, `maximum_number_of_urls`,
  `context_threshold_mode`.

**Non-goals.** Renaming the node or `RETRIEVAL.fetch_candidates`; tuning token
budgets; changing the allow-list; eval runs (advisory, see follow-up).

**Code vs brainstorm disagreements (code wins).**
- `AGENTS.md` and `.github/copilot-instructions.md` are copies of `CLAUDE.md`
  (only the title differs) and carry the same "three Brave batches … trafilatura"
  and `search.py` text; they are updated too.
- `Candidate` is built positionally with three arguments in five test files;
  each gains a fourth argument.

**External API facts relied on** (verified 2026-09-14):
- Endpoint, `q` ≤ 600 chars / 75 words, `count` 1–50, response
  `grounding.generic[] = {url, title, snippets[]}` —
  [API reference](https://api-dashboard.search.brave.com/api-reference/ai/llm_context/get).
- "Use Goggles to restrict context to trusted, authoritative sources" —
  [LLM Context docs](https://api-dashboard.search.brave.com/documentation/services/llm-context).
- Inline allow-list Goggle `$discard\n$site=a.com\n$site=b.com` —
  [Goggles docs](https://api-dashboard.search.brave.com/documentation/resources/goggles),
  [brave-search-skills llm-context](https://github.com/brave/brave-search-skills/blob/main/skills/llm-context/SKILL.md).

## 2. File responsibilities

| File | Responsibility for this change |
|---|---|
| `src/utils/__init__.py` | New empty package marker so setuptools and imports find `utils`. |
| `src/utils/search.py` (from `src/search.py`) | Owns the Brave LLM Context request, Goggle construction, allow-list gate, merge, and length filtering. |
| `src/models.py` | `Candidate` gains `text: str`; `SourcePolicy` loses `batches`; `NoSourcesError` docstring drops "fetch". |
| `src/agents/expert/consts/sources.py` | Drops `SEARCH_BATCHES` and `batches=`. |
| `src/agents/expert/nodes/search_and_fetch.py` | Imports from `utils.search`; calls `search_sources` then synchronous `filter_sources`. |
| `pyproject.toml`, `uv.lock` | `search` leaves `py-modules`; `utils*` joins package discovery; trafilatura removed. |
| root `requirements.txt` | Regenerated compatibility export without trafilatura. |
| `tests/unit_tests/utils/__init__.py` | New empty package marker, matching `tests/unit_tests/agents/`. |
| `tests/unit_tests/utils/test_search.py` (from `tests/unit_tests/test_search.py`) | Moved to mirror `src/utils/search.py`; rewritten for one LLM Context call and `filter_sources`. |
| `tests/unit_tests/test_fetch.py` | Deleted (tests removed code). |
| `tests/unit_tests/agents/expert/consts/test_sources.py` | Batch tests removed. |
| `tests/unit_tests/agents/expert/nodes/test_search_and_fetch.py`, `tests/unit_tests/test_api.py`, `tests/integration_tests/test_expert_graph.py`, `tests/integration_tests/test_orchestrator_graph.py` | New names, `Candidate(..., text)`, synchronous `filter_sources` fakes. |
| `CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md`, `README.md`, `app/README.md` | Describe one LLM Context call and `utils/search.py`. |

## 3. Ordered tasks

### Task 1 — Move the module (no behavior change)

- `git mv src/search.py src/utils/search.py`; create empty `src/utils/__init__.py`.
- `pyproject.toml`: remove `"search",` from `[tool.setuptools] py-modules`; change
  `[tool.setuptools.packages.find] include = ["agents*"]` to `["agents*", "utils*"]`.
- `src/agents/expert/nodes/search_and_fetch.py`: `from utils.search import fetch_sources, search_allowlisted`.
- `git mv tests/unit_tests/test_search.py tests/unit_tests/utils/test_search.py`; create empty
  `tests/unit_tests/utils/__init__.py` (unit tests mirror `src/`).
- `tests/unit_tests/utils/test_search.py`, `tests/unit_tests/test_fetch.py`: `import search` → `from utils import search`.

Validation: `uv sync --locked --dev && make test && make lint`.

### Task 2 — Replace Web Search + scraping with LLM Context, and rename

Interfaces produced: `search_sources(query: str, policy: SourcePolicy) -> list[Candidate]` (async),
`filter_sources(candidates: Sequence[Candidate], policy: SourcePolicy) -> list[Source]` (sync),
`Candidate(title, url, domain, text)`.

**`src/models.py`**

```python
@dataclass(frozen=True)
class Candidate:
    """An allow-listed search result with the text Brave extracted for it."""

    title: str
    url: str
    domain: str
    text: str
```

Remove `batches: tuple[tuple[str, ...], ...]` from `SourcePolicy`. Change the
`NoSourcesError` docstring to "No allow-listed source survived search and filtering."
Change the `SearchUnavailableError` docstring to "The Brave request for this run failed."

**`src/agents/expert/consts/sources.py`**: delete `SEARCH_BATCHES` and the
`batches=SEARCH_BATCHES,` line.

**`src/utils/search.py`** — full replacement body (keeps `_normalize_domain` and
`allowed_domain` exactly as today, including the current debug logging):

```python
"""Allow-listed Brave LLM Context search and source filtering.

This shared boundary names no agent. Callers supply a :class:`SourcePolicy`.
"""

from __future__ import annotations

import logging
import os
from collections import Counter
from collections.abc import Sequence
from urllib.parse import urlparse

import httpx

from models import Candidate, SearchUnavailableError, Source, SourcePolicy

logger = logging.getLogger(__name__)
BRAVE_LLM_CONTEXT_URL = "https://api.search.brave.com/res/v1/llm/context"
BRAVE_TIMEOUT_SECONDS = 10.0
BRAVE_RESULT_COUNT = 50
BRAVE_MAX_QUERY_CHARS = 600
BRAVE_MAX_QUERY_WORDS = 75


# _normalize_domain and allowed_domain: unchanged


def build_query(query: str) -> str:
    """Trim a query to Brave LLM Context's documented limits."""
    words = query.split()[:BRAVE_MAX_QUERY_WORDS]
    while words and len(" ".join(words)) > BRAVE_MAX_QUERY_CHARS:
        words.pop()
    if not words:
        raise ValueError("Query is empty after trimming.")
    return " ".join(words)


def build_goggles(policy: SourcePolicy) -> str:
    """Build an inline Goggle that discards every site outside the allow-list."""
    return "\n".join(
        ["$discard", *(f"$site={domain}" for domain in policy.allowed_domains)]
    )


def merge_candidates(
    candidates: Sequence[Candidate], policy: SourcePolicy
) -> list[Candidate]:
    """Dedupe URLs, cap results per domain, and move paywalled domains last."""
    merged: list[Candidate] = []
    seen_urls: set[str] = set()
    per_domain: Counter[str] = Counter()
    for candidate in candidates:
        if candidate.url in seen_urls:
            continue
        if per_domain[candidate.domain] >= policy.max_per_domain:
            continue
        seen_urls.add(candidate.url)
        per_domain[candidate.domain] += 1
        merged.append(candidate)
    merged.sort(key=lambda item: item.domain in policy.deferred_domains)
    logger.info(
        "Candidate merge completed: input=%d, selected=%d", len(candidates), len(merged)
    )
    return merged


def _parse_candidates(payload: object, policy: SourcePolicy) -> list[Candidate]:
    """Turn ``grounding.generic`` into allow-listed candidates, skipping bad items."""
    grounding = payload.get("grounding", {}) if isinstance(payload, dict) else {}
    results = grounding.get("generic", []) if isinstance(grounding, dict) else []
    candidates: list[Candidate] = []
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        raw_url = item.get("url")
        url = raw_url.strip() if isinstance(raw_url, str) else ""
        domain = allowed_domain(url, policy) if url else None
        if domain is None:
            logger.debug("Dropped unusable or out-of-allowlist result: %r", raw_url)
            continue
        raw_title = item.get("title")
        title = (
            raw_title.strip()
            if isinstance(raw_title, str) and raw_title.strip()
            else "Untitled"
        )
        snippets = item.get("snippets")
        text = "\n\n".join(
            snippet.strip()
            for snippet in (snippets if isinstance(snippets, list) else [])
            if isinstance(snippet, str) and snippet.strip()
        )
        candidates.append(Candidate(title=title, url=url, domain=domain, text=text))
    return candidates


async def search_sources(query: str, policy: SourcePolicy) -> list[Candidate]:
    """Run one allow-listed Brave LLM Context request and merge its results."""
    brave_key = os.getenv("BRAVE_SEARCH_KEY")
    if not brave_key:
        raise SearchUnavailableError("Missing BRAVE_SEARCH_KEY for live search.")
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": brave_key,
    }
    params = {
        "q": build_query(query),
        "goggles": build_goggles(policy),
        "count": BRAVE_RESULT_COUNT,
    }
    try:
        async with httpx.AsyncClient(headers=headers) as client:
            response = await client.get(
                BRAVE_LLM_CONTEXT_URL, params=params, timeout=BRAVE_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("Brave LLM Context request failed: %s", exc)
        raise SearchUnavailableError("The Brave request failed for this run.") from exc
    candidates = _parse_candidates(payload, policy)
    logger.info("Brave LLM Context returned allow-listed results: count=%d", len(candidates))
    return merge_candidates(candidates, policy)


def filter_sources(
    candidates: Sequence[Candidate], policy: SourcePolicy
) -> list[Source]:
    """Keep candidates with enough text, trimmed to the policy's maximum."""
    sources = [
        Source(
            title=candidate.title,
            url=candidate.url,
            text=candidate.text[: policy.max_source_chars],
        )
        for candidate in candidates
        if len(candidate.text) >= policy.min_source_chars
    ]
    logger.info(
        "Source filter completed: candidates=%d, kept=%d", len(candidates), len(sources)
    )
    return sources
```

Notes:
- `asyncio.CancelledError` is a `BaseException`, so it is not caught and still propagates.
- `ValueError` in the `except` covers `response.json()` decode failures only;
  `build_query`'s `ValueError` is raised before the `try` (same as today's
  `build_batch_query`, which the API's query validation prevents in practice).
- `build_batch_query`, `_trim_query`, `_brave_batch`, `_fetch_and_extract`,
  `_extract_sync`, `_extract_text`, `FETCH_*`, `QUERY_TRIM_*`, `MAX_REDIRECTS`,
  `BRAVE_SEARCH_URL`, `BRAVE_RESULTS_PER_QUERY`, and the `asyncio`, `urljoin`,
  `trafilatura` imports are deleted.

**`src/agents/expert/nodes/search_and_fetch.py`**

```python
"""Retrieval node: allow-listed Brave LLM Context search and source filtering."""
...
from utils.search import filter_sources, search_sources
...
async def search_and_fetch(state: PipelineState) -> dict[str, Any]:
    """Search the allow-list and keep sources with enough extracted text."""
    candidates = (await search_sources(state["query"], EXPERT_SOURCES))[
        : RETRIEVAL.fetch_candidates
    ]
    if not candidates:
        raise NoSourcesError(
            "No approved sources were found for this query. Try rephrasing it."
        )
    sources = filter_sources(candidates, EXPERT_SOURCES)[: RETRIEVAL.keep_sources]
    if not sources:
        raise NoSourcesError(
            "None of the approved sources for this query had enough text to use."
        )
    # keep the existing logger.info("search_and_fetch: ...") and `return {"sources": sources}`
```

Edit only the lines shown; do not replace the whole function body.

**Tests** (see §4 for assertions): rewrite `tests/unit_tests/utils/test_search.py`, delete `test_fetch.py`,
edit `test_sources.py`, and update every fake. `filter_sources` is now called without
`await`, so a fake left as `async def` fails with
`TypeError: 'coroutine' object is not subscriptable`. Convert each of these:

| File | Fakes to change |
|---|---|
| `tests/unit_tests/agents/expert/nodes/test_search_and_fetch.py` | `empty` (3rd test's `sources` too) → `def`; `Candidate(..., "reuters.com", "body")`; monkeypatch names at lines 18, 33–34, 49–50 |
| `tests/integration_tests/test_expert_graph.py` | both `sources` fakes (≈ lines 42, 74) → `def`; `Candidate` at 40, 72; monkeypatch names at 45–46, 77–78 |
| `tests/unit_tests/test_api.py` | `sources` fake (≈ line 782) → `def`; `Candidate` at 780; monkeypatch names at 792–793 |
| `tests/integration_tests/test_orchestrator_graph.py` | shared `_geopolitical_sources` (≈ line 69) → `def`; `Candidate` at 66; monkeypatch names at 121–122, 132–133, 158–159, 207, 281, 342–343, 376–377 |

After editing, `grep -rn "async def .*sources\|fetch_sources\|search_allowlisted" app/tests`
must show no `async def` fake bound to `filter_sources` and no old names.

Validation: `uv run pytest tests/unit_tests/utils/test_search.py tests/unit_tests/agents/expert -q`,
then `make test && make lint`, then `make integration_tests` if the `.env` it needs is present.

### Task 3 — Remove trafilatura and update docs

- `uv remove trafilatura` (updates `pyproject.toml` and `uv.lock`), then `uv sync --locked --dev`.
- Regenerate the root compatibility `requirements.txt` with the command in its header:
  `uv export --locked --no-dev --no-hashes --format requirements-txt --no-emit-project -o ../requirements.txt`.
- `CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md`, identical edits:
  - Shared modules: `` `config.py`, `models.py`, `utils/search.py`, `llm.py`, `tracing.py`, and `api.py` ``.
  - Expert sentence: "The expert makes exactly one Brave LLM Context request
    restricted to the allow-list with an inline Goggle, and makes one streamed
    plain-text model call. Expert search, source, and model failures are hard errors;
    do not add degraded fallbacks."
- `README.md` (lines 26–30): "`search_and_fetch` makes one Brave LLM Context request
  restricted to a curated set of domains and keeps the allow-listed pages with
  enough extracted text."
- `app/README.md` (lines 19–25): same sentence; "shared retrieval and LLM boundaries
  are in `src/utils/search.py` and `src/llm.py`."

Validation: `uv sync --locked --dev && make test && make lint`;
`grep -rn "trafilatura\|three Brave\|search_allowlisted\|fetch_sources\|src/search.py" app/src app/tests CLAUDE.md AGENTS.md .github/copilot-instructions.md README.md app/README.md` returns nothing.

## 4. Test and follow-up notes

**`tests/unit_tests/utils/test_search.py` (rewritten)**, `_response(generic)` returns
`{"grounding": {"generic": generic}}` with request URL `search.BRAVE_LLM_CONTEXT_URL`:
- `test_allowed_domain_accepts_subdomains_and_rejects_lookalikes` — kept as is.
- `test_query_limits` — `build_query("word " * 400)` is ≤ 600 chars and ≤ 75 words.
- `test_merge_caps_and_defers` — single list of 3 reuters + 1 ft → first two reuters then ft.
- `test_search_makes_one_llm_context_call_with_goggles` — fake `get` records calls;
  asserts one call, URL == `BRAVE_LLM_CONTEXT_URL`, `params["count"] == 50`,
  `params["goggles"].split("\n")[0] == "$discard"`, the `$site=` set equals
  `set(EXPERT_SOURCES.allowed_domains)`, off-list URL dropped, and
  `snippets=["a", " ", "b"]` becomes `text == "a\n\nb"`.
- `test_search_request_failure_raises` — parametrized: `httpx.ConnectError` raised,
  and a 429 response → `SearchUnavailableError`.
- `test_malformed_items_are_skipped` — non-dict item, non-string url, list title
  (→ "Untitled"), non-list snippets (→ `text == ""`) do not crash.
- `test_search_preserves_cancellation` — fake `get` raises `asyncio.CancelledError`; it propagates.
- `test_filter_sources_applies_char_limits` — 499-char text dropped, 500-char kept,
  25,000-char trimmed to 20,000.

**`test_sources.py`**: delete `test_batches_partition_allowlist`, the `SEARCH_BATCHES`
import, and the `batches` assertion in `test_policy_matches_constants`.

**`test_search_and_fetch.py`**: `test_no_fetched_sources_raises` → fake `filter_sources`
returns `[]` synchronously; `test_sources_are_capped` fake is synchronous.

**Follow-up (advisory, not gating):** run `tests/manual_quality/basic_agent_evaluation.py`
before and after to check whether snippet-based sources thin out expert answers; if so,
raise `maximum_number_of_tokens` in a separate change.

**Correctness review (one reviewer), all accepted:**
- Async fakes bound to the now-synchronous `filter_sources` across four test files → explicit per-file table in Task 2.
- `SearchUnavailableError` docstring still says "every Brave request" → updated in Task 2.
- Root `requirements.txt` still pins trafilatura → regenerated in Task 3.
- Elided node snippet could drop logging/return → explicit "edit only shown lines" note.
- Checked, no change: JSON decode failure → 503 preserved; `utils` package has no name collision; proposed code fits `mypy --strict`.

**Accepted risks (from brainstorm):** big outlets may crowd out small ones with one
call; snippets may fall under `min_source_chars=500` more often; Brave's default
8,192-token budget is roughly 1,000 tokens per kept source.
