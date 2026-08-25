# Rebuilding the GeopoliticAI agentic workflow (simpler + cheaper)

**Started:** 2026-08-25
**Status:** Complete
**Mode:** one question at a time, at the user's request (rounds 1-18)

## Target design

```text
START -> search_and_fetch -> answer -> END
```

**Node 1 — `search_and_fetch` (no LLM call):**
raw user query -> 3 concurrent Brave queries, each a `site:` OR-filter over ~10 of the
~28 allow-listed domains -> merge + dedupe results -> fetch top ~10 pages concurrently
(`httpx.AsyncClient`, ~5s per-request timeout) -> extract article text with `trafilatura`
-> drop every source whose fetch or extraction failed -> keep ~8, uncapped
(~20k char per-source guardrail) -> **zero usable sources raises**.

**Node 2 — `answer` (one LLM call, `gpt-4o-mini`):**
query + the ~8 articles (title, URL, full text) -> streamed markdown. Every factual
sentence carries an inline markdown link built from the source's raw URL. Where sources
conflict, the model must name the conflict and attribute each position rather than
averaging it away. Nothing post-processes the output.

| Metric | Before | After |
| --- | --- | --- |
| `app/src` LOC | 3,056 | ~700 |
| Graph nodes | 15 | 2 |
| LLM calls / run | 6-14 | **1** |
| Brave requests / run | ~15-20 | **3** |
| Page fetches / run | 0 | 10 |
| Python dependencies | 10 | 11 (`+trafilatura`) |
| Languages supported | English + Polish | English only |

## Context verified against the codebase

- `app/src/` was ~3,056 LOC across 24 modules; `app/tests/` ~968 LOC across 11 files.
- **Brave calls per run:** `web_searcher` issued one request *per allowed domain*, 3 domains/lane, 5 lanes = ~15 requests, plus up to 5 combined-query fallbacks. Each domain loop `break`s after the first accepted item, so 15 requests yielded at most 15 sources.
- **No page fetching.** Sources carried only the Brave `description` snippet (`notes`, capped 400 chars, truncated to 220 in analyst prompts). The whole pipeline reasoned over search snippets.
- **LLM calls per run:** 4 analysts + 1 cross_check + 1 compose = 6 minimum; `generic_analyst`'s initial -> retry -> repair ladder made the worst case 14.
- Every agent was `gpt-4o-mini`; `max_completion_tokens` default 16,384.
- **The TRUE-only funnel:** `cross_check_facts` fuzzy-matched verdicts back to claims (`SequenceMatcher` >= 0.85) and stamped `MISLEADING` on anything unmatched; `compose_final` used **only** `TRUE` claims, else emitted canned "no TRUE claims" text. Flagged in the 2026Aug24 session and left unfixed.
- `referee` was pure Python with an **English-only** `LOADED_TERMS` list while the API default infosphere was `polish` — the loaded-language gate was inert on the default path.
- `build_research_plan` was deterministic string concatenation (no LLM) and only `queries[0]` ever reached `web_searcher`.
- `supervisor` was ~350 LOC of pure-Python report assembly, including regex "consensus entity" inference that only logged a warning.
- Graph compiled with no checkpointer/store; `thread_id` was configuration context only.
- CI does **not** reference root `requirements.txt` — `.github/workflows/unit-tests.yml` runs `uv sync --locked --dev` with `working-directory: app`. Compose builds `./app` and `./frontend`, never the root. The guidance docs claim otherwise and are wrong.
- Root `main.py` imports a nonexistent `geopoliticai` package; root `Dockerfile` runs `uvicorn geopoliticai.api:app`, also nonexistent; root `requirements.txt` pins unused `tavily-python` and `langgraph>=0.2,<1.0`, which *excludes* the `langgraph>=1.0.0` the app requires.
- Prior session artifact: `docs/brainstorming/2026Aug24_brainstorm_v1.md` -> `docs/plans/2026Aug24_plan_for_cleaning_repo_v3.md`.

## Settled decisions

- **Q1 — Product invariant** — Target shape is **two nodes / logical gateways: (1) search the web, (2) answer the query.** Explicitly: *no panel of experts, no judge.* _(rationale: the multi-agent debate structure is not worth its maintenance cost.)_
  - Deletes the 4 analyst agents + retry/repair ladders, `referee`, `cross_check_facts` + fuzzy matcher, the TRUE-only funnel, `Claim` / `FactCheckResult` / `RefereeReport`, and most of the 350-LOC `supervisor`.
- **Q2 — Sourcing and language** — (1) **Drop the Polish infosphere entirely**; English sources and English output only. (2) **One merged allow-list**, initially 9 domains = left(3) + centrist(3) + right(3); the `fact` lane (Reuters/AP/FactCheck.org) and `people` lane (Reddit/X/Threads) are dropped with it. _(rationale: bias-diverse sourcing survives as a retrieval constraint but stops being an output or agent structure.)_ Superseded on width by Q8.
  - Deletes `POLISH_INFOSPHERE_SOURCES`, `detect_language`, `normalize_language`, `_POLISH_DIACRITICS`/`_POLISH_STOPWORDS`, `_VERDICT_BADGE_PL`, every Polish prompt branch, and the `people`/`fact` lane plumbing. Touches `api.py`, `cli.py`, `frontend/index.html`.
- **Q3 — Retrieval depth** — **Fetch and extract real page text** for the top N results, not snippets. _(rationale: with the referee and fact-checker deleted, context content is the entire grounding mechanism; 200-char blurbs guarantee the model fills gaps from parametric memory.)_
  - Accepted: one new HTML-extraction dependency, N parallel fetches, ~2-5s added latency, and graceful handling of paywalls (The Economist is hard-paywalled).
- **Q4 — Framework** — **LangGraph is mandatory.** `StateGraph`, `langgraph.json`, `langchain-core`, `langchain-openai` and the `astream_events` streaming path all stay. _(rationale: user constraint, not up for trade.)_
  - Recommendation to drop to plain async Python was declined. Simplification therefore comes from **state shape and node count**, not dependency removal. Still available: drop the `Annotated[..., operator.add]` reducers (nothing writes concurrently any more), shrink `PipelineState` to ~3 keys, collapse `llm.py` to a single chain wrapper, and reconsider `nodes/runtime_config.py` now that `language`/`infosphere` are gone.
- **Q5 — Output contract** — **Free text only, and no deterministic fallbacks anywhere.** The answer node writes the finished markdown itself, including inline source links; nothing post-processes it. _(rationale: the model's output should be the product, not a reshaped derivative of it.)_
  - Read as a **cross-cutting principle**: deletes `supervisor` (350 LOC), `render.py`, `_VERDICT_BADGE_*`, `_split_direct_answer_and_details`, `_ensure_short_answer_prefix`, `_fallback_claims_from_sources`, `_fallback_for_no_true_claims`, `_fallback_from_true_claims`, the `ErrorRecord` / `errors` state channel, and every canned degraded-answer string.
  - Rejected: a hybrid returning a deterministic `sources` array alongside the prose.
- **Q6 — Failure semantics** — **Hard-fail all three paths.** Zero in-allowlist results, all fetches failing, or an LLM error each surface as an error to the client — never as a degraded or fabricated answer.
  - A source whose fetch fails is **dropped**, not downgraded to its Brave snippet. Snippets stop being an evidence path entirely.
  - Raises the visible "no answer" rate, which promoted allow-list width from a tunable to a real decision (Q8).
  - Rejected: never-fail / answer from parametric memory — indistinguishable from a sourced answer in free-text output.
- **Q7 — Query construction** — **Deterministic; no LLM query-planner.** The raw user query goes to Brave with `site:` filtering. _(rationale: keeps the pipeline at exactly one LLM call.)_
  - Resulting shape: node 1 = search + fetch + extract (zero LLM calls); node 2 = answer (one LLM call).
  - Consequence: recall rests entirely on the raw query plus allow-list width. Nothing compensates for a conversationally-phrased question.
- **Q8 — Allow-list width** — **Widen the flat list to ~25-30 domains**, weighted toward outlets that *report* (wire services, mainstream news with known leans) rather than the all-analysis roster, still spread across the spectrum. _(rationale: free at runtime — all domains ride in `site:` filters — and the only remaining lever on the error rate after Q6 and Q7 removed the other two.)_
  - Reconfirmed: **one lane in the graph.** The left/centrist/right labels are only a curation guide for choosing entries; they never appear in the graph, state, prompts, or output.
- **Q9 — Model choice** — **Stay on `gpt-4o-mini`.** _(rationale: cheapest option, and a single config string — the most reversible decision in the design.)_
  - Argument made and not taken: dropping 6-14 calls to 1 frees roughly a 10x per-token budget at equal spend; `gpt-4o-mini` now carries the entire product alone over long context with no judge and no fallback, and long-context source attribution is where small models degrade.
- **Q10 — Evidence budget** — **Generous.** Fetch ~10, keep ~8, article text **uncapped**. Prompt lands around ~15k tokens. _(rationale: analytical questions often turn on a passage deep inside a long essay.)_
  - Accepted risk: with `gpt-4o-mini` and 8 long documents, source attribution is the likely failure mode, and nothing downstream catches it.
  - Implementation flags: fetch concurrently via `asyncio.gather` + `httpx.AsyncClient` with a ~5s per-request timeout; "uncapped" still needs a ~20k char/source guardrail so an occasional long report cannot blow the prompt to ~100k tokens.
- **Q11 — Citation / grounding** — (1) **Source labelling: URLs only** — no numeric or lane-prefixed IDs anywhere; the prompt supplies title + URL and the model emits inline markdown links. (2) **Citation rule: strictest** — every factual sentence must carry an inline link. _(rationale: the answer prompt is the only grounding control left, so attribution errors must at least be visible.)_
  - Accepted risk: the model transcribes raw URLs by hand; mistyped long URLs ship as broken links with nothing to catch them.
  - Kills the ID round-trip that produced the old failure mode.
- **Q12 — Surfacing disagreement** — **Required in the prompt.** Where sources conflict, the model must name the conflict and attribute each position rather than averaging into "mixed results". _(rationale: nothing else in the pipeline uses the cross-spectrum spread; without this the curation is paid for and discarded.)_
  - Rejected: a mandated closing "where sources disagree" section, which would be a fixed output shape contradicting Q5.
  - Noted risk: a small model told to find disagreement may manufacture it. Mitigation is conditional wording ("*where* they conflict").
- **Q13 — API surface** — **Keep both endpoints, one shared implementation.** Node 2's answer generator is the single source of truth: streaming yields chunks, sync does `"".join(chunks)`. Rate limiting, prompt logging and error mapping happen in exactly one place.
  - Falling out of earlier decisions: `infosphere` leaves the request model; `report_mode`/compact mode dies with `supervisor`; `_NODE_LABELS_PL`/`_NODE_LABELS_EN` collapse to two English labels; errors become real error events rather than degraded 200s.
- **Q14 — Migration + test strategy** — **One decisive in-place rewrite on a branch.** Delete `src/nodes/**`, `planning.py`, `render.py`; rewrite `graph.py`, `models.py`, `llm.py`, `search.py`; edit `api.py`, `config.py`, `cli.py`; `database.py` untouched. Tests rewritten in the same pass. `main` stays working because the work is on a branch. _(rationale: reverses the round-1 greenfield suggestion — the modules a parallel `v2/` would duplicate are exactly the ones being kept, and the deleted code is already cleanly separable.)_
  - Rejected: incremental-with-green-tests, because the existing tests encode the design being removed.
  - Test plan: `test_database.py` (148) and `test_config_env.py` (105) survive nearly intact; `test_api.py` (243) and `test_search_enforcement.py` (135) rewritten against new contracts; the rest deleted. New suite concentrates on (1) domain-allowlist enforcement — can an out-of-list URL ever reach the prompt, (2) the three hard-fail paths from Q6, (3) the API contract for both endpoints including streaming events and error shapes.
- **Q15 — Prompt logging / Postgres tier** — **Keep as-is.** `database.py`, `asyncpg`, and the Postgres service all stay. _(rationale: with every automated quality check deleted, the prompt log is the only remaining way to find out whether the app produces good answers.)_
- **Q16 — Legacy root files** — **Keep `main.py`, root `Dockerfile`, root `requirements.txt`; update them after the refactor** rather than deleting them now.
  - Post-refactor follow-up owed: fix all three to match the new structure, and correct the false "CI still references the root requirements.txt" claim in `CLAUDE.md`, `AGENTS.md`, and `.github/copilot-instructions.md`.
- **Q17 — Brave call shape** — **~3 batched OR queries of ~10 domains each**, run concurrently, results merged and deduped. _(rationale: keeps each query safely inside Brave's query-length/term limits — exact values still to verify — and avoids the silent-truncation failure mode of one ~550-char OR filter; also buys result diversity, since a single ranked list over 28 domains tends to be dominated by the 2-3 best-SEO publishers.)_
  - Replaces the per-domain loop and its combined-query fallback. Brave requests per run: ~15 -> 3.
  - Diversity matters specifically because Q12 requires surfacing disagreement; eight Reuters articles cannot disagree with each other.
  - Flagged, not chosen: **Brave Goggles** (custom ranking definitions passed as an API parameter rather than operator text) would solve this without any query-length concern. Worth verifying against current Brave docs.
- **Q18 — HTML extraction library** — **`trafilatura`.** _(rationale: boilerplate removal is load-bearing under Q10's uncapped 8-document prompt — naive `.get_text()` yields 2-4x the real article text and makes eight documents look structurally alike, which is exactly the condition under which a small model loses track of which document said what.)_
  - Bonus: returns nothing on a paywall stub rather than returning the paywall's marketing copy, so the source drops cleanly under Q6.

## Design tree

- Rebuild the agentic workflow
  - **Product invariant** — SETTLED: two nodes, search -> answer. No experts, no judge.
    - **Bias-diverse sourcing** — SETTLED: kept as retrieval constraint, one flat English list
      - **Retrieval depth** — SETTLED: fetch + extract page text
        - **HTML extraction library** — SETTLED: `trafilatura`
      - **Framework** — SETTLED: LangGraph mandatory
        - **Output contract** — SETTLED: free text only, no deterministic fallbacks
          - **Failure semantics** — SETTLED: hard-fail, never degrade
            - **Query construction** — SETTLED: deterministic, no planner. One LLM call total.
              - **Allow-list width** — SETTLED: ~25-30, news-weighted, one flat list, one lane
                - **Brave call shape** — SETTLED: 3 batched OR queries, concurrent
                - **Model choice** — SETTLED: `gpt-4o-mini`
                  - **Evidence budget** — SETTLED: fetch 10, keep 8, uncapped
                    - **Citation / grounding** — SETTLED: URLs only, inline links, per-sentence
                      - **Surfacing disagreement** — SETTLED: required, conditionally worded
                        - **API surface** — SETTLED: both endpoints, one shared generator
                          - **Migration + test strategy** — SETTLED: decisive in-place rewrite on a branch
                            - **Prompt logging / Postgres** — SETTLED: keep as-is
                            - **Legacy root files** — SETTLED: keep, update after refactor

## Current frontier (open questions)

_Empty. Every branch visited._

## Carried into implementation as flags, not decisions

- Verify Brave's actual query-length / term limit before fixing the batch size at ~10 domains.
- Verify whether **Brave Goggles** is available on the current plan; it would replace the `site:` batching entirely.
- Pin the ~20k char/source guardrail so "uncapped" cannot blow up the prompt.
- Expect broken inline links from hand-transcribed URLs (Q11) and wrong-source attribution (Q9 + Q10) — neither is detectable in-pipeline by design.
- Post-refactor: fix the three root files and the false CI claim in the three guidance docs (Q16).
- Per project rules, the refactor must update `AGENTS.md`, `CLAUDE.md`, and `.github/copilot-instructions.md` together. `ai_tools_tables.md` is unaffected — no skills, hooks, or agent configuration change.

## Round log

### Round 1
**Q1 — Product invariant.** Asked whether the four-lane bias spectrum is the product or scaffolding.
Recommended keeping the lanes and collapsing the calls. **User answered stronger than offered:** simplify to ~2 nodes — search, then answer. No experts, no judge.

### Round 2
**Q2 — Bias-diverse sourcing.** Asked whether the domain allow-lists survive as a retrieval constraint now that the lanes are dead as agents, arguing the allow-list is the last quality control standing once the judge is gone.
Recommended keeping it as a hard filter with one Brave call and a wider list. **User answered:** keep it, drop the Polish infosphere entirely, and merge left+centrist+right into one flat 9-domain list (dropping `fact` and `people`).

### Round 3
**Q3 — Retrieval depth.** Asked snippets-only vs fetch-pages vs selective-fetch, noting that deleting the judge makes context content the sole grounding mechanism, and flagging The Economist paywall and extraction slop.
Recommended fetching. **User agreed.**

### Round 4
**Q4 — Framework.** Asked whether LangGraph survives a 2-node acyclic pipeline with no checkpointer, no reducers and no branching; argued the SSE progress machinery reduces to two `yield`s.
Recommended plain async Python. **User answered: LangGraph is mandatory.** Constraint accepted.

### Round 5
**Q5 — Output contract.** Asked free-text vs structured+renderer vs hybrid, arguing the structured option's appeal is bogus because the search node already knows its own sources and the LLM round-trip is the current failure mode.
Recommended the hybrid. **User answered free text, and wider: no deterministic fallbacks at all.**

### Round 6
**Q6 — Failure semantics.** Enumerated the three failure paths created by allow-list + fetching + no-fallbacks, and argued "degrading is fine, faking is not".
Recommended hard-fail on zero evidence, degrade on partial. **User answered: hard-fail all three.**

### Round 7
**Q7 — Query construction.** Asked whether node 1 gets an LLM query-planner, arguing a ~200-token planning call protects the expensive half of the run now that bad recall means a hard error.
Recommended adding the planner. **User answered: deterministic, one LLM call total.**

### Round 8
**Q8 — Allow-list width (revisit).** Re-opened Q2's "9 domains" because Q6 and Q7 landed afterwards and both compound the zero-result rate. User first read this as reintroducing ideological experts; clarified that the allow-list is a flat list of URL strings in `config.py` that never touches the graph, then re-explained the mechanics with a worked example (a German-coalition query returning 0 usable sources).
Recommended widening. **User agreed** — ~25-30 domains.

### Round 9
**Q9 — Model choice.** Argued that removing 5-13 calls frees ~10x per-token budget for free, and that `gpt-4o-mini` now carries the whole product with no safety net over long context.
Recommended moving up a tier. **User answered: stay on `gpt-4o-mini`.**

### Round 10
**Q10 — Evidence budget.** Gave prompt-size arithmetic for four configurations and noted that fitting the context window is not the constraint — small-model attention over many long documents is.
Recommended the balanced option. **User answered: generous, uncapped.**

### Round 11
**Q11 — Citation / grounding.** Asked how sources are labelled in the prompt and how strict the citation rule is; argued strictness matters because `gpt-4o-mini` over 8 long documents has attribution error as its likely failure and nothing can detect it.
Recommended numbered IDs plus the strictest rule. **User answered: URLs only (no IDs), strictest rule.**

### Round 12
**Q12 — Surfacing disagreement.** Argued that without this instruction the design reduces to "summarize 8 pages" and the curated allow-list buys nothing visible in the output.
Recommended requiring it. **User agreed.**

### Round 13
**Q13 — API surface.** Asked whether the sync endpoint survives, noting the two paths duplicate rate limiting, logging, error handling and sanitizing, and have already drifted.
Recommended keeping both behind one implementation. **User agreed.**

### Round 14
**Q14 — Migration + test strategy.** Mapped module-by-module fate (~70% deleted, survivors are exactly what a parallel package would duplicate) and argued the existing tests encode the design being removed.
Recommended a decisive in-place rewrite, reversing the round-1 greenfield suggestion. **User agreed.**

### Round 15
**Q15 — Prompt logging / Postgres tier.** Argued the prompt log is the last remaining feedback mechanism now that every automated check is deleted; asked whether the table is actually ever read.
Recommended keeping it. **User agreed.**

### Round 16
**Q16 — Legacy root files.** Verified against CI and compose that all three root files are dead and broken, and that the guidance docs' warning about CI depending on root `requirements.txt` is false.
Recommended deleting them. **User answered: keep them, update after the refactor.**

### Round 17
**Q17 — Brave call shape.** Asked how the `site:` filter is sent given ~28 domains. User asked for a deeper explanation of the `site:` operator; explained it as query text rather than an API parameter, contrasted the per-domain loop against one OR query on request count / diversity / relevance, and flagged the silent-truncation risk plus Brave Goggles as an unverified alternative.
Recommended 3 batched queries. **User agreed.**

### Round 18
**Q18 — HTML extraction library.** Argued boilerplate removal is load-bearing under an uncapped 8-document prompt into a small model.
Recommended `trafilatura`. **User agreed.**
