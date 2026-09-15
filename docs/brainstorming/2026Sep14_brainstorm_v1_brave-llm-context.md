# Replace Brave Web Search + scraping with Brave LLM Context in the search module

**Started:** 2026-09-14
**Status:** Complete — awaiting user approval (naming proposal to confirm)
**Mode:** batch
**Classification:** Bounded

## Target design

Replace Brave Web Search plus page fetching/trafilatura extraction with a single
[Brave LLM Context](https://api-dashboard.search.brave.com/api-reference/ai/llm_context/get)
call that returns pre-extracted page text. The module moves to `app/src/utils/search.py`.

```
search_sources("Taiwan chips", EXPERT_SOURCES)
  GET https://api.search.brave.com/res/v1/llm/context
      q="Taiwan chips"          (trimmed to 600 chars / 75 words)
      goggles="$discard\n$site=bbc.com\n$site=reuters.com\n…"
      count=50
  → reads grounding.generic[] {url, title, snippets}
  → drops off-allow-list URLs, joins snippets into text
  → dedupes URLs, caps 2 per domain, moves paywalled domains last
  → [Candidate(title, url, domain, text)]

filter_sources(candidates, EXPERT_SOURCES)
  → drops text shorter than min_source_chars, trims to max_source_chars
  → [Source(title, url, text)]
```

### Files

| File | Change |
|---|---|
| `src/utils/__init__.py` | New, empty. |
| `src/utils/search.py` | Moved from `src/search.py`. New endpoint and goggles; functions renamed. `allowed_domain` and `merge_candidates` stay (`merge_candidates` takes a single list). Deleted: `build_batch_query`, `_brave_batch`, `_fetch_and_extract`, `_extract_sync`, `_extract_text`, `FETCH_*` constants, redirect handling. |
| `src/models.py` | `Candidate.text: str` added; `SourcePolicy.batches` removed. |
| `src/agents/expert/consts/sources.py` | `SEARCH_BATCHES` removed. |
| `src/agents/expert/nodes/search_and_fetch.py` | `from utils.search import search_sources, filter_sources`. |
| `pyproject.toml` / `uv.lock` | Remove `"search"` from `py-modules`; add `"utils*"` to `packages.find.include`; remove trafilatura. |
| `CLAUDE.md`, `README.md`, `app/README.md` | "three Brave batches + trafilatura" → "one LLM Context call"; shared-module list names `utils/search.py`. |

### Errors

- Missing `BRAVE_SEARCH_KEY` or HTTP failure → `SearchUnavailableError`, no fallback.
- No allow-listed results → the node's existing `NoSourcesError`.

### Testing

- Rewrite `tests/unit_tests/test_search.py` with a mocked httpx client, asserting:
  exactly one call to `/llm/context` with correct `goggles`; off-list URLs dropped;
  snippets joined into `text`; HTTP failure raises `SearchUnavailableError`;
  `filter_sources` applies min/max character limits.
- Delete `tests/unit_tests/test_fetch.py` and the batch-partition test in
  `tests/unit_tests/agents/expert/consts/test_sources.py`.
- Add `text=` wherever tests build a `Candidate`; update monkeypatch names in
  `test_api.py`, `test_search_and_fetch.py`, `test_expert_graph.py`,
  `test_orchestrator_graph.py`.
- Validate with `make test` and `make lint` from `app/`.

## Context verified

- Endpoint: `GET https://api.search.brave.com/res/v1/llm/context`, header `X-Subscription-Token`.
  `q` max 600 chars / 75 words; `count` default 20 (1–50); `maximum_number_of_tokens`
  default 8192 (1024–32768); `maximum_number_of_urls` default 20 (1–50).
- Response: `grounding.generic[] = {url, title, snippets[]}`; snippets may be text or JSON-serialized structured data.
- Brave docs: "Use Goggles to restrict context to trusted, authoritative sources"; guidance favors one call with filtering configured once.
  Inline allow-list goggle: `$discard\n$site=a.com\n$site=b.com`. `site:` query operators are converted to Goggles internally.
  `context_threshold_mode=strict` recommended only when precision > recall.
  Sources: [API ref](https://api-dashboard.search.brave.com/api-reference/ai/llm_context/get),
  [LLM Context docs](https://api-dashboard.search.brave.com/documentation/services/llm-context),
  [Goggles docs](https://api-dashboard.search.brave.com/documentation/resources/goggles),
  [brave-search-skills llm-context](https://github.com/brave/brave-search-skills/blob/main/skills/llm-context/SKILL.md).
- Current code: `src/search.py` uses `/res/v1/web/search`, three site-filtered batches, then fetches pages and extracts with trafilatura.
- Only production caller: `src/agents/expert/nodes/search_and_fetch.py` (caps candidates at `RETRIEVAL.fetch_candidates=10`, sources at `RETRIEVAL.keep_sources=8`).
- `src/utils/` does not exist. `pyproject.toml` lists `search` in `py-modules` and finds packages with `include = ["agents*"]`. Dockerfile copies all of `src/`.
- `EXPERT_SOURCES`: `max_per_domain=2`, `min_source_chars=500`, `max_source_chars=20_000`.

## Settled decisions

- **Q1 — Text carrier:** `Candidate` gains `text` (edits `models.py`) _(rationale: no hidden module state)_
  - Challenged on: breaks "one file" and every test constructing `Candidate` → held.
- **Q2 — Remove fetching and trafilatura entirely** _(rationale: CLAUDE.md forbids degraded fallbacks)_
  - Challenged on: snippets are excerpts, more sources may fall under 500 chars → held.
- **Q3 — One call with a Goggles allow-list** _(rationale: Brave's own guidance; 1/3 quota)_
  - Challenged on: large outlets may crowd out small ones; batch contract, `SEARCH_BATCHES`, CLAUDE.md, and tests change → held.
  - `context_threshold_mode` left at Brave default (lenient) to avoid more `NoSourcesError`.
- **Naming:** `search_allowlisted` → `search_sources`; `fetch_sources` → `filter_sources` _(proposal — user asked for better naming and suggested `filter_sources`; to confirm)_
  - Challenged on: `filter_sources` for the Brave-calling function would hide its network call → proposed mapping above.
- **Location:** `src/search.py` → `src/utils/search.py`
  - Challenged on: a one-module `utils/` risks becoming a dumping ground and diverges from flat shared modules → pending user confirmation with approval.

## Design tree

- Endpoint swap — SETTLED (LLM Context)
  - Text carrier — SETTLED (Q1: `Candidate.text`)
  - Fetch/extraction path — SETTLED (Q2: remove)
  - Call shape — SETTLED (Q3: one call + goggles)
    - `context_threshold_mode` — SETTLED (default)
    - Token/URL budgets — SETTLED (Brave defaults; flag below)
- Public naming — SETTLED pending confirmation
- Module location — SETTLED (`utils/search.py`)

## Current frontier (open questions)

None.

## Carried as flags, not decisions

- Large outlets may crowd out small ones with a single call; the 2-per-domain cap only partly offsets it.
- Snippets are excerpts; more sources may fall below `min_source_chars=500`.
- Brave's default total budget is 8,192 tokens (~1,000 tokens per source for 8 sources). If expert answers get thinner, raise `maximum_number_of_tokens`.

## Round log

### Round 1 — Q1: text carrier; Q2: remove fetching; Q3: batch shape
Lean A/A/A. **User answered:** Q1 A, Q2 A, asked what Brave's docs recommend for Q3.

### Round 2 — Q3 (revised): one call vs three batches with Goggles
Docs recommend Goggles and a single configured call. Lean A (weak). **User answered:** B, follow Brave's guides. Pushed back on crowding → held.

### Round 3 — naming and location
**User asked:** better name for `search_allowlisted` (e.g. `filter_sources`); move module to `utils/search.py`. Proposed `search_sources` / `filter_sources`; pushed back on single-module `utils/` → move retained.
