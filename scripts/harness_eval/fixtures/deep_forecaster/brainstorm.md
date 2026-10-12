# Deep forecaster agent: a council-style forecasting path built from the forecaster list, the deep expert, and the AI council prototype

**Started:** 2026-09-30
**Status:** Complete — approved by the user 2026-09-30 (round 23); handed off to `/rs-plan-from-brainstorm`
**Mode:** batch (similar questions per round, default)

## Target design

A new opt-in route, `"forecast"`, sends an **explicitly requested** forecast to a new agent,
`agents/deep_forecaster/`. The agent is a **fixed LangGraph workflow with one Deep Agent step**
(Q27, following the user's pasted migration guidance): only research is autonomous; every later
step runs once, in a fixed order, with typed state between steps.

1. `research` — a `deepagents` **lead** (gpt-5-mini, `reasoning_effort="low"`, built per call)
   dispatches parallel **scout** subagents over the forecasters it judges relevant: their own 12
   websites, plus Gemini's notes on Wojczal's YouTube videos. The scouts' tools record every source
   read; the node returns those typed sources, never the agent's final text.
2. `draft_claims` — one structured call over **all** sources → 2–4 dated, checkable claims,
   validated in code.
3. `council_round_1` / `council_round_2` — a **7-member Delphi vote** (OpenAI gpt-5-mini, Google
   `gemini-3.8-flash`, 5 free OpenRouter models; neutral, identical instructions, anonymous as
   "Member 1…7"); each member reads every source and votes for / against / unsure per claim with
   reasons and evidence ids; round 2 shows each member the others' anonymous round-1 ballots.
   Failed members drop out; the vote continues while a quorum holds.
4. `tally` — code: ACCEPTED / REJECTED at ≥ 2/3 of members voting (rounded up), else UNRESOLVED.
5. `write` — gpt-5-mini writes the analysis from the claims, the tally, the members' reasons, and
   the sources.
6. `verify` — code checks, then appends the exact vote list in full wording ("Claim 1 … ACCEPTED
   (5 of 7 voted for)", "Member 3: against — … [link]").

The answer reaches the browser once as a `notice`. A forecast costs **20 quota units** (a user's
whole day), may run **up to 15 minutes**, has no mid-run pause (Q28), and follow-ups are ordinary
turns.

### §1 Architecture and data flow

```text
orchestrator:  START -> classify -> expert | deep_expert | deep_forecaster | chat | reporter -> END

deep_forecaster node -> forecast(standalone_query, writer) -> str
  forecaster graph (own StateGraph, invoked from the node; checkpointing off for the whole tree):
  START -> research -> draft_claims -> council_round_1 -> council_round_2 -> tally -> write -> verify -> END
           |  Deep Agent: lead --task--> scout, scout, scout (parallel)
           |  tools: search_forecaster / read_source / ask_video, recording into ResearchRun
           +-> {"sources": [...]}
```

- `ForecastState` (TypedDict): `question`, `sources`, `claims`, `ballots_round_1`,
  `ballots_round_2`, `tally`, `draft`; nodes return partial updates, never mutate.
- Each council round is **one** node that calls the members concurrently (`asyncio.gather`,
  per-member timeout), not one node per member.
- Routing: `"forecast"` only on an explicit request for a forecast/prediction; never on the
  classifier's own judgement; "deep dive: will X happen?" without one stays `"deep"`; follow-ups
  are not forecasts; a question about a forecast just given goes to `"other"` (chat) — F5.
- The orchestrator invokes the forecaster from its own node (as the expert, deep expert, and
  reporter): its state shares only the question with the orchestrator's.

### §2 Components

- `agents/deep_forecaster/consts/forecasters.py` — the 13 forecasters as editorial data: id,
  display name for bylines, domains, YouTube channel (Wojczal), X handle (for later); no
  strengths/weaknesses (user-only notes). `FORECASTER_SOURCES` `SourcePolicy` over the 12 readable
  domains (krzysztofwojczal.pl, fiia.fi, khas.edu.tr, jiss.org.il, belfercenter.org, ifri.org,
  tsinghua.edu.cn, carnegieendowment.org, eai.or.kr, instituteofgeoeconomics.org,
  saiia.org.za, project-syndicate.org — F9).
- `agents/deep_forecaster/state.py` — `ForecastState`; `ResearchRun` (search budget, candidates,
  sources, video notes) that the tools record into.
- `agents/deep_forecaster/tools.py` — plain `@tool`s independent of who calls them:
  `search_forecaster(forecaster, query)` restricts the site filter to that forecaster's domains;
  `read_source(url)` only for URLs a search returned, output includes the page's byline;
  `ask_video(url, question)` only for YouTube URLs a search returned — `gemini-3.8-flash` takes the
  public video URL in "static" mode with a very low `fps` (~120k tokens per hour) and returns the
  relevant passages as text, stored as a source labelled "Gemini's notes on the video"
  (model-produced, not verbatim). Shared search budget with a soft stop, as the deep expert.
- `agents/deep_forecaster/council.py` — roster: gpt-5-mini via OpenAI; `gemini-3.8-flash` via
  Gemini's OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`,
  beta; native `google-genai`/`langchain-google-genai` already in the lock as a fallback); five
  `:free` models via `ChatOpenAI(base_url="https://openrouter.ai/api/v1")`; `Ballot`/`Vote`
  schemas (structured output by tool calling); ballot validation (one vote per claim, known
  evidence ids, for/against need evidence); one round; quorum; tally. Seat→model mapping logged,
  never shown.
- `agents/deep_forecaster/nodes/` — `research.py` (builds the lead + `scout` subagent spec per
  call; returns `run.sources`), `draft_claims.py`, `council.py` (round 1 and round 2),
  `tally.py`, `write.py`, `verify.py` (checks + vote-list rendering).
- `agents/deep_forecaster/graph.py` — `build_graph()` wiring the fixed edges;
  `agents/deep_forecaster/forecast.py` — `forecast()` entry: wall cap, invoke with checkpointing
  off (`NO_CHECKPOINTER_CONFIG` pattern), return the verified answer.
- `agents/deep_forecaster/{config,prompts}.py`, `consts/progress.py` — count-only progress labels
  emitted by each node (planning, scouting k searches / n sources / m videos, drafting claims,
  council round 1 of 2, round 2 of 2, writing, checking).
- Orchestrator: `"forecast"` in `Destination`/`RouteDecision`, classifier prompt rules, node
  `nodes/deep_forecaster.py`, edge.
- `api.py`: `"forecast"` in `RESEARCH_DESTINATIONS`; per-destination cost (forecast 20, deep 5,
  else 1) with the advisory headroom read for any cost > 1; refusal "A forecast needs 20 research
  turns; you have N left today." `deep_forecaster` never in `ANSWER_NODES`.
- `config.py`: `FORECAST_TURN_COST = 20`; `OPENROUTER_API_KEY` and `GEMINI_API_KEY` required at
  API startup (F10).
- Frontend: `STREAM_TIMEOUT_MS` raised to 15 min (applies to every turn).
- `CLAUDE.md`: graph diagrams, forecaster paragraph, env vars, cost, 15-min limit.

### §3 Errors and limits

| Situation | Outcome |
|---|---|
| Wall cap (~14 min, under the browser's 15) | hard error, 504 (`ResearchLimitError`), naming the step reached |
| No source read (e.g. a topic none of the 13 covers) | hard error, 422 (`NoSourcesError`), after `research` |
| `draft_claims` returns invalid claims (no date, not 2–4, duplicates) | hard error, 502 |
| A council member fails (429, empty reply, invalid ballot, timeout) | dropped; vote continues if quorum holds; answer shows "N of 7 voting" |
| Fewer members than quorum (F7) | hard error, 502 |
| `verify` fails: a link not among the sources; prose contradicts the tally (F11) | hard error, 502 |
| Search budget spent | soft stop: message to the model |
| Gemini video call refused / over quota / timed out | soft stop: message to the scout (F2) |
| Brave outage | as the deep expert handles it |
| Fewer than 20 units left | 429 before the run, no counter touched |

### §4 Testing and evals

- Unit (mirroring `src/`): tools (per-forecaster site filter, allow-list, only-returned URLs,
  byline passthrough, soft stops), `research` with a fake agent returning recorded sources,
  `draft_claims` validation, council (ballot validation, quorum, round-2 anonymity), `tally` at 5
  of 7 and 4 of 5, `write`, `verify` checks and vote-list rendering,
  `tests/unit_tests/agents/deep_forecaster/test_graph.py` (fixed edges), orchestrator routing to
  `"forecast"`, API cost 20 and refusal; Vitest for the new stream timeout.
- Evals: orchestrator rows (explicit forecast, paraphrase, plain "will X?" → geopolitical, "deep
  dive: will X?" → deep, "and South Korea?" after a forecast → geopolitical, "why did Member 3…"
  → other); `evals/deep_forecaster.py` on recorded synthetic forecaster sources (claims dated and
  checkable, citation provenance, prose-vs-tally in code, unanimity share recorded — F4); a
  backtest subset on questions resolved after 2026-06 with hand-written pre-event sources and a
  no-sources leakage probe (F6). Eval runs spend the site's shared OpenRouter free budget (F8).

### §5 Operations

`OPENROUTER_API_KEY` and `GEMINI_API_KEY` added to the VPS `.env` by hand; the OpenRouter
account needs ≥ $10 of credits ever bought (F1) and its free-model privacy setting must allow the
roster's providers; Gemini billing per F13 (it serves the council seat and `ask_video`); roster
churn is handled by editing `council.py`'s roster.

## Context verified

- **Forecaster list** — `tmp/pl/geopolitical_forecasters.md` (Polish) is one table of 13 real,
  living analysts, one per country (PL, FI, TR, IL, UK, FR, DE, CN, RU, KR, JP, IN, ZA). Columns:
  name, country, school/specialisation, "infosphere" (blog, X, YouTube, or think-tank pages:
  krzysztofwojczal.pl, FIIA, Kadir Has, JISS, Belfer, IFRI, Tsinghua, Carnegie, EAI, IOG Tokyo,
  SAIIA), strengths, weaknesses (each row names the analyst's known bias). A sibling
  `tmp/pl/geopolitical_experts.md` exists and was not asked for.
- **Council prototype** — `origin/ai_council:prototypes/ai_council.py` (commit `748f6da`, plus
  `prototypes/test_ai_council.py`; the branch is otherwise far behind `main`). Standalone
  LangGraph `StateGraph`: `search` (Tavily, commented out, replaced by 10 mocked records) →
  `propose` (member_a drafts 1–2 atomic claims) → `start_round` (rotating opener) → up to
  `messages_per_round=4` peer messages (`PeerMessage{to, message, reply_to, evidence_ids}`, a
  member addresses a peer, scheduling guard makes every member speak) → `begin_vote` fan-out →
  3 parallel `Ballot`s (support/oppose/abstain per claim, evidence ids required for
  support/oppose) → `tally` (≥2 support = accepted, ≥2 oppose = rejected, else unresolved) →
  loop until `max_rounds=2` or all resolved after `min_rounds=1`. Members are anonymous aliases
  over three different vendor models via OpenRouter (`openrouter/free` default), JSON-schema
  structured output over raw httpx. **On any model/validation error it degrades** (filler peer
  message; abstain ballot) — this repo forbids degraded fallbacks for the expert path.
- **Deep expert** (`agentic_backend/src/agents/deep_expert/`) — `deepagents.create_deep_agent`,
  gpt-5-mini `reasoning_effort="low"`, `search_sources`/`read_source` tools over `search.py`
  with `EXPERT_SOURCES`, shared 5-search budget (soft stop), `RubricMiddleware` gpt-4o-mini grader
  (3 rounds, last draft ships), 480 s hard wall cap (`ResearchLimitError`, 504), answer delivered
  once as a `notice`, progress labels carry counts only, built per turn, checkpointing off for the
  whole tree (`NO_CHECKPOINTER_CONFIG`). Smoke run 2026-09-29: one gpt-5-mini agent turn ≈ 40–50 s;
  5 searches is what fits under 480 s.
- **Time ceiling** — nginx and the browser abort at 600 s (`agents/reporter/config.py`); every
  deep path must finish well inside it.
- **Integration points a new route touches** — `Destination` literal and `RouteDecision`
  description (`orchestrator/state.py`), `CLASSIFY_SYSTEM_PROMPT` (`orchestrator/prompts.py`),
  routing map (`orchestrator/graph.py`), a node in `orchestrator/nodes/`, `RESEARCH_DESTINATIONS`
  and the `counted` cost branch (`api.py` ~113, ~611: cost is `DEEP_RESEARCH_TURN_COST` only when
  destination is `"deep"`), `DEEP_RESEARCH_TURN_COST = 5` (`config.py`), `ANSWER_NODES` must not
  gain the new node (notice delivery).
- **Sources** — `EXPERT_SOURCES` allow-lists 28 English-language news/think-tank domains
  (Reuters … Brookings, AEI, Hoover). None of the forecasters' infosphere domains is on it; X and
  YouTube pages are not article pages trafilatura can extract.
- **Providers** — production is OpenAI-only (`llm.py`, `langchain_openai`); `OPENROUTER_API_KEY`
  is used only by `evals/helpers/{judge,run}.py`. Required API env vars:
  `OPENAI_API_KEY`, `BRAVE_SEARCH_KEY`, `DATABASE_URL`, `JWT_SIGNING_KEY`.
- **OpenRouter reach** — the evals already call OpenRouter through the OpenAI-compatible client
  (`evals/helpers/judge.py`: `provider="openai"`, `base_url="https://openrouter.ai/api/v1"`), so a
  production OpenRouter member needs no new SDK, only `ChatOpenAI(base_url=..., api_key=...)` and a
  new required env var.
- **OpenRouter free tier (docs, fetched 2026-09-30)** — `:free` models: **20 requests/min** and
  **50 requests/day** with < $10 credits ever bought, **1,000/day** with ≥ $10. Limits are per
  **account**, global across keys (extra keys don't help); over the cap → HTTP 429. OpenRouter keeps
  **separate privacy settings for free models** (whether to allow providers that may train on
  inputs); per-model data policy unverified. The evals' judge
  (`nvidia/nemotron-3-super-120b-a12b:free`) spends from the same account if it shares the key.
  `judge.py` notes a rate-limited or failed free call can come back as HTTP 200 with
  `choices: null`, and that `openrouter/free` was abandoned for a pinned model.
- **Free models listed today** (`GET https://openrouter.ai/api/v1/models`, 2026-09-30: 464 models,
  20 free). General-purpose text models by distinct vendor: `nvidia/nemotron-3-ultra-550b-a55b:free`
  (also super-120b, lightning, nano), `qwen/qwen3.8-27b:free`, `google/gemma-4-31b-it:free` (also
  26b), `thinkingmachines/inkling:free` (also small), `dots-studio/dots-3-note-preview:free`,
  `inclusionai/ling-3.0-flash-sante:free`. Excluded as unfit: `liquid/lfm-2.5-2.6b` (2.6B),
  `poolside/laguna-*` and `cohere/north-mini-code` (code models), `nvidia/nemotron-3.5-content-safety`
  (classifier), `google/lyria-3-*` (music), `stealth/space-bunny-alpha` (stealth, temporary),
  `openrouter/free` (random router). Only qwen3.8, dots-3, nemotron-3-super, liquid and the router
  advertise `structured_outputs`; all candidates advertise `tools` (so structured output via tool
  calling works for all). So **about 6 distinct free vendors + OpenAI = 7 seats** today.
- **Call arithmetic (prototype pattern, 7 members, 6 free)** — every member speaks once and votes
  once per round → 12 free calls/round, 2 rounds → **~24 free calls per turn** → ~41 forecast turns
  per day site-wide at 1,000/day, **~2 per day at 50/day**. Discussion messages are sequential
  (each reads the transcript): 7 per round × free-model latency (unmeasured, 5–30 s assumed) ≈
  35–210 s per round, before research.
- **Infosphere probe (2026-09-30, scratch script over the app's own `search.py`)** — one Brave
  `site:` query (author surname + topic) per domain, top 3 fetched with trafilatura
  (`min_source_chars=500`):

  | domain | hits | readable/3 | chars |
  |---|---|---|---|
  | krzysztofwojczal.pl | 5 | 3 | 1,704 · 1,337 · 20,000 |
  | fiia.fi | 5 | 2 | 3,570 · 1,740 |
  | khas.edu.tr | 7 | 1 | 730 |
  | jiss.org.il | 10 | 3 | 527 · 535 · 643 |
  | belfercenter.org | 9 | 3 | 3,001 · 20,000 · 6,054 |
  | ifri.org | 7 | 3 | 1,638 · 1,638 · 8,463 |
  | tsinghua.edu.cn | 6 | 3 | 10,858 · 6,936 · 618 |
  | carnegieendowment.org | 9 | 3 | 8,107 · 1,779 · 7,711 |
  | eai.or.kr | 6 | 2 | 3,095 · 20,000 |
  | instituteofgeoeconomics.org | 7 | 3 | 1,245 · 9,640 · 1,821 |
  | project-syndicate.org (Chellaney's column) | 9 | 2 | 7,239 · 3,213 |
  | saiia.org.za | 9 | 2 | 1,275 · 590 |
  | x.com | 9 | 1 | 773 (login/boilerplate) |
  | youtube.com | 10 | 3 | 2,295 ×3 identical (page chrome, no transcript) |

  Think-tank sites are searchable and mostly readable; many short hits (500–1,700 chars) look
  like profile/listing pages rather than articles (unverified by eye). **X posts and YouTube
  videos are not usable** through search + trafilatura: Masala's and Chellaney's X and
  Wojczal's YouTube need another path (X API; captions/transcripts). Author-name queries return
  pages *about* an author as well as *by* them.
- **No stored corpus exists** — `docs/brainstorming/2026Sep22_brainstorm_v1_youtube-transcripts-rag.md`
  (In progress, never implemented) sketched an agentic-owned Postgres table with full-text search
  (no pgvector in `postgres:16-alpine`); nothing under `src/` stores fetched articles today.
- **What enforces the time limit today** — the browser: `frontend/chat/src/lib/sse.ts:32`
  `STREAM_TIMEOUT_MS = 10 * 60 * 1000` aborts *every* turn at 10 min (the browser does not know
  the route before the request). nginx: `proxy_read_timeout 600s` (`frontend/nginx.conf:107`,
  `nginx.local.conf:55`) is the gap between two reads, not a total, so a stream that emits
  progress at least every 600 s is not cut. Backend: no total run cap in `api.py`; each agent
  carries its own (deep expert 480 s). JWT access token: 15 min
  (`web_backend/politicalagent/settings.py:150`), checked once at request start, so a long
  stream is not cut by expiry. No client-disconnect handling in `api.py` (grep: none); what a
  closed tab does to a running turn is unverified.
- **X (researched 2026-09-30, third-party summaries)** — official X API: the free tier is
  write-only and closed to new signups since 2026-02-06; pay-per-use is the default (reported
  ~$0.005 per post read, ~$0.010 per user read); Basic ~$200/mo. Scraper libraries (`twscrape`)
  need pools of logged-in X accounts, break when X changes private endpoints, and violate X's
  terms; Nitter's repo was archived. Sources: zernio.com/blog/twitter-api-pricing,
  opentweet.io/how-to/x-api-pay-per-use-explained, scrapfly.io/blog/posts/best-twitter-scrapers-github.
  In the list only Masala (X only) and Chellaney (X; also Project Syndicate) depend on X.
- **YouTube (researched 2026-09-30)** — youtubetotranscript.com is a web tool whose
  programmatic offer is a separate paid API (transcriptapi.com). The free `youtube-transcript-api`
  Python library works from home IPs, but YouTube blocks cloud/VPS IPs (`RequestBlocked`/
  `IpBlocked`); its docs recommend paid rotating residential proxies. Sources:
  github.com/jdepoix/youtube-transcript-api, transcriptapi.com/blog/fix-youtube-transcript-api-errors.
  Only Wojczal lists YouTube. A long video transcript exceeds `max_source_chars=20,000`.
- **Free YouTube route (Gemini API docs, fetched 2026-09-30)** — the Gemini API accepts a public
  YouTube URL as video input: "The YouTube URL feature is in preview and is available at no
  charge"; public videos only; **free tier ≤ 8 hours of YouTube video per day**; Gemini 2.5+ takes
  up to 10 videos per request (ai.google.dev/gemini-api/docs/video-understanding). The SDKs are
  already in the lock as deepagents transitives (`google-genai 2.25.0`, `langchain-google-genai
  4.4.0`). Needs a new Google AI key; free-tier content terms and per-minute token quota for a long
  video unverified. Finding the videos: Brave `site:youtube.com` returned 10 hits for Wojczal
  (probe); the YouTube Data API is also free (10,000 units/day, search = 100 units).
- **Free X route probe (2026-09-30)** — Brave `Carlo Masala site:x.com` with `extra_snippets`:
  results were his profile bio, other people's posts about him, "JavaScript is not available"
  boilerplate, and his own posts reduced to his display name (77 chars); newest dated 2025-04.
  **Brave snippets do not carry his post text.** Remaining free routes violate X's terms
  (logged-in account-pool scrapers) → no free, terms-compliant, working X route found.
- **Gemini "watching" a video (docs, fetched 2026-09-30)** — the YouTube-URL input processes the
  video itself, not its captions: frames at 1 fps (66 tokens each) + audio (32 tokens/s) ≈ **100
  tokens per second** → a 1-hour video ≈ 360k tokens; clipping (`start_offset`/`end_offset`) and a
  lower `fps` exist in "static" mode. Latency for a 1-hour video unmeasured.
- **Caption transcripts (probe 2026-09-30, from the dev machine's home connection)** —
  `youtube-transcript-api` fetched Polish transcripts of 4 Wojczal videos (found via Brave
  `site:youtube.com`) in **1.0–1.2 s each**: ~52 min → 44,983 chars (auto-generated), ~60 min →
  47,286, ~68 min → 61,734, ~167 min → 149,513 (manual captions). Whether YouTube blocks the
  **VPS** IP is unverified (the library's docs say cloud IPs are commonly blocked). Transcripts
  exceed `max_source_chars=20,000`.
- **VPS transcript probe (2026-09-30, run by Claude at the user's request)** — `ubuntu@politicalagent.eu`
  (51.254.212.152, OVH); `deploy@` rejected this machine's key; `ubuntu` has no Docker access and
  the host Python 3.14 has no `ensurepip`, so the probe ran from pure-Python wheels copied to a
  `mktemp` dir on `PYTHONPATH` (dir removed; verified none left). `youtube-transcript-api 1.2.4`:
  **both videos `RequestBlocked` (0.7–0.8 s)** — the same videos succeed from the home
  connection. **YouTube blocks the production IP.**
- **Google AI Pro vs the Gemini API** — ai.google.dev/gemini-api/docs/google-ai-plans: "Google AI
  plan benefits for developer usage apply only within the Google AI Studio web interface. Direct
  use of the Gemini API (such as using API keys…) is billed and managed separately"; subscribers
  with a GCP project and Cloud Billing are eligible for monthly Cloud credits via the Google
  Developer Program — reported as **$10/month for Pro** (9to5google, letsdatascience; the amount
  is not on Google's page read). Current models (pricing page): `gemini-3.8-flash` free tier yes,
  paid $0.75 / $3.75 per 1M in/out (through 2026-12-31); `gemini-3.5-flash-lite` $0.30 / $2.50.
  Free-tier per-project limits are shown only in the AI Studio dashboard. Estimate: a council seat
  reading ~100k tokens × 2 rounds ≈ $0.15 per forecast on paid Flash → ~65 forecasts per $10.
- **Grok / xAI X Search (docs.x.ai/developers/tools/x-search, fetched 2026-09-30)** — a
  server-side `x_search` tool on the Responses API (`/v1/responses`; xAI SDK, OpenAI Responses
  API, Vercel AI SDK): "keyword search, semantic search, user search, and thread fetch on X";
  `allowed_x_handles` (≤ 20), `excluded_x_handles`, `from_date`/`to_date`, image/video analysis;
  returns `response.citations` (post URLs). **"Billed at $5 per 1k posts fetched and $10 per 1k
  user profiles fetched, in addition to token costs."** xAI's billing FAQ mentions only prepaid
  credits; a third-party blog's "$150/month free credits for data sharing" is **not** confirmed
  by xAI's docs. Not available through OpenRouter. Estimate: 20–40 posts per forecast ≈
  $0.10–0.20 plus Grok tokens (unmeasured).
- **Author-name search is not authorship** — the X probe returned posts *about* Masala by others;
  the site probe returned profile pages. Naming an author needs the page's own byline.
- **Brave rate** — no throttle in `search.py`; the deep expert measured ~1.1 s per search. The
  plan's per-second limit (which bounds parallel scouts) is unverified.
- **Branch note** — this design builds on the deep-expert stack's tip (`deep-expert/05-deep-evals`,
  `06e4bb2`). Mid-session (round 9) the working tree was switched to `deep-expert/02-quota-cost`
  with an uncommitted `agentic_backend/src/db/web/sql.py` edit, and `CLAUDE.md` there predates the
  deep expert. Untouched by this session.
- **Context room on the roster** — every roster model's context is ≥ 262,144 tokens (qwen3.8-27b,
  gemma-4-31b, ling-3.0-flash: 262k; dots-3: 512k; inkling, nemotron-3-ultra: ~1M; gpt-5-mini:
  OpenAI's own limit), so ~100k-token member prompts fit. OpenRouter's free limits count
  requests, not tokens. Free-provider latency on a 100k-token prompt is unmeasured.
- **Unrelated prior art** — `docs/magi_lcr_adaptation_plan.md` describes an older left/centre/right
  analyst + referee design against a pipeline that no longer exists; not an input here.

## Settled decisions

- **Q1 — Answer shape** — a council verdict on forecast claims, as the prototype: each claim
  ACCEPTED / REJECTED / UNRESOLVED with its vote count _(rationale: user's choice; follows the
  prototype)_
  - Challenged on: evidence cannot "directly confirm" a future event, so the prototype's vote
    rule would leave most claims UNRESOLVED → not revised (challenge posed twice, user moved on).
  - Consequences: the vote needs a forecast-specific meaning (Q7); no probabilities in the answer.
- **Q2 — Council members** — ~~anonymous schools of thought derived from the forecaster list~~
  **REVISED round 11 (user's own proposal; confirmation posed round 12, user moved on):** 7 neutral members, one per model, identical
  instructions; the forecaster list is only the scouts' list of whose writing to collect, and its
  strengths/weaknesses columns are notes for the user that no agent sees. No member ever speaks
  as, or invents views for, a real named person _(rationale: "the list of forecasters is only to
  get data from internet, AI council should be separate")_
  - Correction (round 6): the round-3 record said "no real names ever appear in answers"; Q2
    only ruled out named *voices*. Citing a forecaster's real published piece is Q16.
  - Challenged on: lens briefs on one model converge (3–0 votes) → answered by Q4 (different
    vendors per seat).
  - Consequences (original): lens briefs from the list; Q8 opened. **Superseded by the revision:**
    no lens briefs; the list feeds only `FORECASTER_SOURCES` (domains, bylines, X handles, YouTube
    channel); the council's diversity rests entirely on Q4's vendors.
- **Q11 — Deliberation** — Delphi: round 1 all members vote independently in parallel with
  reasons and citations; round 2 each sees the others' anonymous votes and reasons and may revise;
  then tally _(rationale: user's choice; parallel, ~12 free calls/turn, two waits)_
  - Challenged on: the prototype's direct peer challenges disappear → accepted in the question's
    "against"; no further objection.
  - Consequences: no `PeerMessage` scheduling; the prototype's `Ballot`/`tally` survive.
- **Q10 — Evidence** — a dedicated, very deep scout gathers as much as possible written by /
  related to the 13 forecasters; then a claims-drafting agent; then the council votes
  _(rationale: "we want really good input data"; the scout is the most important part)_
  - Challenged on: depth vs the time limit → became Q14; scope → Q15.
- **Q12 — Final answer on screen** — both: a written analysis on top, the exact vote list
  underneath, in full wording ("Claim 1", "Member 1", no "C1"-style abbreviations)
  _(rationale: readable and exact)_
  - Challenged: no objection beyond the question's own "against" (prose and list could disagree
    → the prose must be checked against the tally in code).
- **Q14 — When the scout runs** — during the question, "for now"; a forecast turn may run up to
  15 minutes _(rationale: no library subsystem yet; 15 min buys the scout ~10 min)_
  - Challenged on: the browser aborts every turn at 10 min (`sse.ts:32`), so raising it affects
    all turns; a closed tab likely loses a long run and its quota → not revised (user moved on).
  - Consequences: `STREAM_TIMEOUT_MS` ≥ 15 min (all turns); the forecaster's own wall cap
    (~14 min) is a hard error like `ResearchLimitError`; progress events must flow at least every
    600 s for nginx; the library (option B) stays a possible later subproject.
- **Q15 — Scout scope** — the 13 forecasters' own sites only (think tanks, blog, column), no
  general news outlets, no open web _(rationale: the forecasters' voice is the point)_
  - Challenged on: a topic none of them covers (e.g. Latin America) finds nothing and fails
    (422); evidence is only as fresh as each forecaster's latest piece → not revised (user moved on).
  - Consequences: a new `FORECASTER_SOURCES` `SourcePolicy` in the agent's `consts/`; the
    allow-list principle holds.
- **Q16 — Naming forecasters** — the answer names the real author and outlet when a point rests on
  their real published piece; members stay anonymous _(rationale: accurate credit, more useful
  links)_
  - Challenged on: readers may take the name as the forecaster's own forecast on the question;
    plus a byline check (round 7).
- **Q18 — Scout shape** — the lead agent (the claims drafter) plans and dispatches several topic
  scouts at once, reads their findings, can send a scout back for a gap, then drafts the claims —
  the deep expert's main-agent + subagent pattern _(rationale: user's choice; reuse, fills gaps)_
  - Challenged on: coverage depends on the lead's judgement → Q19.
  - Consequences: `deepagents` main agent with a custom scout subagent spec; scout tools over
    `search.py` with `FORECASTER_SOURCES`; shared search budget like `ResearchRun`.
- **Q17 — X and YouTube** — YouTube in the first version through the Gemini API's free
  YouTube-URL input; X later (Grok's X Search is the known paid route) _(rationale: free only)_
  - Challenged on: site-wide 8 h/day free quota and a preview feature → round 9.
  - Consequences: a Google AI key (new required env var, or optional with the tool disabled —
    decide at plan time); a scout tool that finds a forecaster's videos and asks Gemini about one.
- **Q19 — Coverage** — the lead picks which forecasters are worth checking for the question
  _(rationale: speed and focus)_
  - Challenged: no objection beyond the question's own (unconsidered forecasters are never checked).
- **Q6 — Routing trigger** — only an explicit request for a forecast; never on the classifier's own
  judgement (same rule as "deep") _(rationale: a forecast costs up to 15 min and several units)_
  - Challenged: no objection beyond the question's own (users must know the word; no button).
  - Consequences: `"forecast"` in `Destination`, `RouteDecision` description, classifier prompt,
    orchestrator eval rows (explicit, paraphrase, plain "will X happen?" negative).
- **Q7 — Vote meaning** — "for" = the claim is more likely than not by its date; "against" = less
  likely; "unsure" = the sources are too thin to lean. ACCEPTED at ≥ 2/3 of members voting "for"
  (rounded up: 5 of 7, 4 of 5), REJECTED at ≥ 2/3 "against", else UNRESOLVED _(rationale: simple,
  keeps the prototype's three stances)_
  - Challenged: no objection beyond the question's own (51% and 95% cast the same vote).
- **Q20 — Council input** — every member reads everything the scouts read (full text, ~100k
  tokens), plus the claims _(rationale: the council judges independently of the lead)_
  - Challenged on: latency and prompt-injection surface on free models (round 10).
- **Q13b — Claims per forecast** — 2–4; the lead decides from the evidence _(rationale: user's
  choice)_
  - Challenged: no objection beyond the question's own (vote list up to 7 × 4 = 28 lines).
- **Q8 — Member slant** — members are neutral; the list's strengths/weaknesses columns are
  information for the user only, never given to an agent _(rationale: user's choice)_
  - Challenged: no objection (it follows from the Q2 revision).
- **Q6c — Follow-ups** — ~~a same-topic follow-up stays a forecast~~ **REVISED by Q25:**
  follow-ups are never forecasts; each forecast must be asked for explicitly
  - Challenged on (round 13): a question about the forecast would start a new forecast; then
    Q25 showed a 20-unit follow-up forecast can never be afforded → reversed.
- **Q21 — Member labels** — the answer shows "Member 1"…"Member 7" only; the seat→model mapping is
  logged for the operator (traces), never shown to users or to other members _(rationale: votes
  judged on reasons, not brands; stable across roster churn)_
  - Challenged: no objection.
- **Q23 — Evals** — the structure checks (routing incl. follow-ups, claims are dated and
  checkable, prose matches the tally in code, citations point to sources read, unanimity rate)
  plus a backtest on questions that have already resolved _(rationale: measure whether the
  council forecasts well)_
  - Challenged on: training-data leakage (a model may remember the outcome) → guards in round 14.
- **Q24 — Overall shape (SUPERSEDED by Q27, round 23)** — "for now": one `deepagents` lead agent dispatches the scouts, drafts
  2–4 claims, calls a `convene_council` tool that runs the 7-member Delphi vote and returns the
  tally, then writes the answer; code appends the vote list _(rationale: user's choice; least code)_
  - Challenged on: the lead could re-run the council until it likes the verdict, or skip it →
    guards proposed round 15.
  - Consequences: no LangGraph council graph; the council is a plain async function inside the
    tool (7 parallel calls per round, tally in code — the prototype's `Ballot`/`tally` logic).
- **Q22/Q25 — Cost** — a forecast spends 20 units from both counters (the whole per-user day);
  follow-ups are normal turns and are refused by the quota after a forecast; chat stays free
  _(rationale: "when user will ask follow up question it will reach limit" — forecasts are rare
  by design)_
  - Challenged on: a user who spent 1 unit earlier cannot forecast that day; the sticky follow-up
    could never run → user chose to reverse Q6c rather than lower the cost.
  - Consequences: site ceiling 500 → ≤ 25 forecasts/day, inside OpenRouter's ~83.
- **Q24 guards** — the council tool runs at most once per turn; a turn whose council never ran is
  a hard error; the council reads sources from the turn's record, the lead passes only claims
  _(user: "yes")_
- **Q17c — Reading YouTube (supersedes Q17b)** — Gemini (`gemini-3.8-flash`) processes the public
  video and returns the relevant passages as text; no new vendor or key _(rationale: the VPS is
  blocked by YouTube; Gemini is already in the design)_
  - Challenged: no objection beyond the question's own (slow, token-heavy, preview); latency and
    token use join the F3 smoke run.
- **Q17b — Reading YouTube (superseded by Q17c)** — caption transcripts through the free
  `youtube-transcript-api` library, not Gemini video input _(rationale: "super time effective" — ~1 s per video vs ~360k
  tokens per hour of video)_
  - Challenged on: works only if YouTube doesn't block the VPS; the probe ran from a home
    connection → F12 (probe on the VPS first).
- **Q26 — Gemini seat** — `gemini-3.8-flash` replaces `google/gemma-4-31b-it:free` as the Google
  seat; still 7 seats, one per vendor _(rationale: user has Google AI Pro; a stronger Google seat)_
  - Challenged on: AI Pro covers AI Studio only, not API keys; the $10/month Cloud credit needs a
    billed project with a card → F13.
  - Consequences: `GEMINI_API_KEY` required; roster = gpt-5-mini, gemini-3.8-flash,
    nemotron-3-ultra, qwen3.8-27b, inkling, dots-3-note-preview, ling-3.0-flash-sante.
- **Q27 — Overall shape (supersedes Q24 B)** — hybrid: the forecaster is its own fixed LangGraph
  `StateGraph` (`research → draft_claims → council_round_1 → council_round_2 → tally → write →
  verify`) with typed `ForecastState`; only `research` is a Deep Agent (lead + parallel scouts)
  _(rationale: user's pasted guidance — autonomy only where planning is open-ended; the council runs
  exactly once by construction; per-step tests; cheap later changes such as a claim-approval pause)_
  - Challenged: no objection beyond the question's own (more structure before the first forecast
    runs).
  - Consequences: claims move from the research lead to `draft_claims` (Q13 revised); Q24 B's
    guards pruned; `convene_council` tool removed; each council round is one node using
    `asyncio.gather`.
- **Q28 — Human approval of the claims** — no pause; ask once, get the answer _(rationale: user's
  choice)_
  - Challenged: no objection; `draft_claims` validates claims in code (dated, 2–4, distinct).
- **Design principles (round 21, from the user's pasted guidance)** — (1) tools are plain
  functions/`@tool`s independent of whether an agent or a graph node calls them; (2) important
  state is explicit and typed (`ForecastState`: question, sources, claims, ballots per round,
  tally, draft, validation errors), never only in prompts or the virtual filesystem; (3) autonomy
  only where planning is genuinely open-ended (research) _(rationale: keeps the path from a
  Deep Agents prototype to an explicit LangGraph workflow cheap)_
  - Challenged: no objection.
- **Q3 — Council size** — "as many as possible": one seat per distinct vendor in the Q4 roster
  (7 today) _(rationale: user's choice; maximise diversity)_
  - Challenged on: 7 seats ≈ 24 free calls/turn under the prototype's pattern → ~41 forecasts/day
    site-wide at 1,000/day, ~2 at 50/day; sequential discussion may not fit 600 s → user deferred
    the arithmetic to the architecture questions ("this is more deep questions").
  - Consequences: the per-turn call count and time budget are decided by the architecture
    (Q10/Q11); if they don't fit, the seat count is the tuning knob (flag).
- **Q4 — Models** — one member on OpenAI directly (`gpt-5-mini`), the rest free OpenRouter models,
  one per vendor _(rationale: real disagreement comes from different training)_
  - Challenged on: free models churn, rate-limit (per-account 20/min, 50 or 1,000/day), and may
    train on inputs → held; roster approved as proposed.
  - Roster: OpenAI `gpt-5-mini`; `nvidia/nemotron-3-ultra-550b-a55b:free`;
    `qwen/qwen3.8-27b:free`; `google/gemma-4-31b-it:free`; `thinkingmachines/inkling:free`;
    `dots-studio/dots-3-note-preview:free`; `inclusionai/ling-3.0-flash-sante:free`. **Superseded in part by Q26:** `google/gemma-4-31b-it:free` → `gemini-3.8-flash`.
  - Consequences: `OPENROUTER_API_KEY` becomes a required production env var (startup check,
    VPS `.env`); OpenRouter members reached through `ChatOpenAI(base_url=...)`; structured output
    via tool calling, since 5 of 7 don't advertise `structured_outputs`.
- **Q9 — A member fails mid-turn** — continue if a quorum still votes, and the answer says how
  many voted _(rationale: with 6 free members, all-or-nothing makes failure common)_
  - Challenged on: first deliberate exception to "no degraded answers"; a partial council's
    verdict isn't the full council's → accepted as stated in the question; no further objection.
  - Consequences: a quorum number (flag); below quorum is a hard error; failed members are
    counted and shown ("4 of 5 voting; 2 unavailable").

## Design tree

- Product: what the user gets back — SETTLED: council verdict on claims (Q1)
  - What a vote means for a claim about the future — OPEN (opened by Q1 B)
  - Answer sections (claims + verdict + reasons + citations; summary?) — OPEN (opened by Q1 B)
- Council membership: how the forecaster list is used — SETTLED (revised): neutral members, one
  per model; the list feeds only the scouts (Q2)
  - Council size — SETTLED: one seat per vendor, 7 today (Q3)
    - Which lenses fill 7 seats out of 13 rows — PRUNED by the Q2 revision (no lenses) (Q3b)
    - Does a member carry a known bias — SETTLED: neutral; list columns are user-only notes (Q8)
    - Does the user see which AI each member is — SETTLED: no, "Member 3" only (Q21)
  - Models — SETTLED: 1 OpenAI + 6 free OpenRouter vendors, roster approved (Q4); Google seat
    later changed to `gemini-3.8-flash` (Q26)
    - A Gemini seat — SETTLED: `gemini-3.8-flash` replaces the Gemma seat (Q26)
    - A member fails mid-turn — SETTLED: quorum (Q9)
- Architecture (round 4)
  - Where the council's evidence comes from — SETTLED: a dedicated, very deep "scout" subagent
    that gathers as much as possible written by / about the 13 forecasters (Q10)
    - Per-member research — PRUNED: 7 tool loops on free models exceed 20 req/min per account
    - When the scout runs — SETTLED: during the question; forecasts may run up to 15 min (Q14)
    - What counts as "related to the experts" — SETTLED: the forecasters' own sites only (Q15)
    - X posts and YouTube videos — SETTLED: YouTube now, X later (Q17)
      - How YouTube is read — SETTLED: Gemini processes the video (Q17c; transcripts ruled out by
        the VPS block)
    - Naming forecasters — SETTLED A (Q16); byline guard proposed, not objected (flag)
    - Scout shape — SETTLED: the drafter leads and dispatches topic scouts, deep expert pattern (Q18)
      - Must every forecaster be covered every time? — SETTLED: no, the lead picks (Q19)
  - How the council deliberates — SETTLED: Delphi (Q11)
    - What a vote means for a future claim; threshold — SETTLED: more likely than not by the
      claim's date; accepted/rejected at ≥ 2/3 of those voting, rounded up (Q7)
    - What each member reads before voting — SETTLED: everything the scouts read (Q20), pending
      challenge
    - Who drafts the claims — REVISED by Q27: a `draft_claims` node over all sources (was: the
      research lead, Q13); how many — SETTLED: 2–4, decided by that step (Q13b)
    - Rounds, caps, fit under 600 s — waits on Q10/Q11
  - Who writes the answer the user reads — SETTLED: prose + exact vote list, full wording (Q12)
- Routing trigger — SETTLED: explicit forecast request only (Q6)
  - "Deep" + "forecast" in one request — PRUNED: follows from Q6 (an explicit forecast request
    goes to the forecaster; "deep dive: will X happen?" without one stays "deep") (Q6b)
  - Sticky follow-ups after a forecast — REVISED by Q25: not sticky; every forecast explicit (Q6c)
    - A follow-up *about* the forecast just given ("why did Member 3 vote against?") — proposed:
      never a new forecast (Q6c challenge, round 13)
- Quota cost — SETTLED: 20 units; follow-ups not sticky (Q22 + Q25)
- Error handling — proposed default: repo rule (hard errors, no prototype-style abstain/filler
  fallbacks); to confirm
- Waiting experience — proposed default: deep expert pattern (count-only progress, one `notice`);
  to confirm
- Evals — SETTLED: structure checks + a backtest on resolved questions (Q23)
  - Backtest leakage and source rules — proposed guards (Q23 challenge, round 14)
- Overall shape — SETTLED: hybrid — fixed LangGraph workflow, Deep Agent only for research (Q27,
  supersedes Q24 B)
  - Design principles from the pasted guidance — ADOPTED: tools independent of the agent;
    important state explicit and structured; autonomy only where planning is open-ended
  - Human approval of the claims before the council votes — SETTLED: no pause (Q28)
  - Q24 B guards — PRUNED: the graph guarantees one council run after drafting

## Current frontier (open questions)

_(empty — design §1–§5 and flags F1–F13 awaiting the user's approval, round 23)_

## Carried as flags, not decisions

Numbered for the approval round (F1–F11); unnumbered items below are older notes kept verbatim.

- **F1** OpenRouter account ≥ $10 credits before launch (50 vs 1,000 free requests/day).
- **F2** A Gemini video call refused / over quota / timed out → soft stop; the forecast continues
  on websites.
- **F3** Smoke run before fixing caps: free-model latency on ~100k-token prompts, and Gemini's
  latency and token use on a 1-hour video; reject votes citing unknown evidence.
- **F4** Unanimity safeguard: eval records the unanimous-vote share; revisit if most are unanimous.
- **F5** A question about the forecast just given goes to chat.
- **F6** Backtest guards (post-2026-06 questions, hand-written pre-event sources, leakage probe).
- **F7** Quorum ≥ 5 of 7; is the OpenAI member mandatory?
- **F8** Evals share production's OpenRouter free budget.
- **F9** project-syndicate.org added for Chellaney (his column; not in the list) — keep?
- **F10** `GEMINI_API_KEY` required at API startup (it now backs a council seat, not an optional
  tool).
- **F12** ~~Run the transcript probe on the VPS~~ — **done round 19: blocked** → Q17c.
- **F13** Gemini billing: start on the free tier if its AI Studio limits cover ≥ 50 council
  requests/day (≤ 25 forecasts × 2 rounds) plus the video calls and a ~120k-token video within the
  per-minute token limit; otherwise a billed project using the AI Pro $10/month
  credit, with a budget alert. Free-tier inputs may be used by Google to improve products.
- **F11** No `RubricMiddleware` grader (the deep expert has one): the `verify` node checks in code;
  the prose-vs-tally check mechanism is decided at plan time.

- **Backtest guards (Q23 challenge)** — questions resolved after 2026-06; hand-written pre-event
  sources; a no-sources leakage probe drops questions a model already answers; ~10 questions is a
  smoke signal. Posed yes/no in round 14, not answered, not objected.

- **Q6c "about the forecast" rule** — proposed: only a new question about the future on the same
  topic stays a forecast; a question about the forecast just given ("why did Member 3 vote
  against?") goes to chat. Posed yes/no in round 13, not answered, not objected.
- **Eval spend shares production's free budget** — backtest and council evals call the same free
  OpenRouter models; with one account, an eval run eats the site's 1,000/day.

- **Unanimity safeguard (Q2 revision)** — with identical neutral instructions and identical
  evidence, disagreement comes only from model differences. The eval records the share of
  unanimous votes; if most votes are unanimous, revisit (e.g. varied instructions). Posed yes/no in
  round 12, not answered, not objected.

- **Q20 guards** — proposed with the round-10 challenge (latency of ~100k-token prompts on free
  models; prompt-injection surface): measure free-model latency in a smoke run before fixing caps;
  code rejects a vote citing an evidence id it was not given. Yes/no not answered, not objected.
  Confirm at design approval.

- **Gemini video quota soft stop (Q17 challenge)** — proposed: when the site-wide free 8 h/day is
  spent, the video tool returns "video reading unavailable today" and the forecast continues on
  websites. Posed yes/no in round 9, not answered, not objected. Confirm at design approval.

- **Byline guard for Q16** — proposed: name an author only when the page's own byline
  (trafilatura metadata) matches the forecaster; otherwise name the outlet. Posed as a yes/no in
  round 7, not answered, not objected. Confirm at design approval.

- **OpenRouter credits** — unanswered: has the account bought ≥ $10 of credits? Decides 50 vs
  1,000 free requests/day for the whole site. Must be ≥ $10 before launch; verify with
  `GET /api/v1/key` (`free_model_daily_requests`).
- **Quorum number** — proposed ≥ 5 of 7 voting; decide at plan time. Consider requiring the
  OpenAI member (the most reliable) so a quorum is never all-free or all-OpenAI.
- **Seat count vs budget** — if Q10/Q11 don't fit 600 s or the daily request budget at 7 seats,
  seats are the knob.
- **Free-model data policy** — per-model training/logging terms unverified; the OpenRouter free
  privacy setting must allow the roster's providers.

- **Forecasters' sites fetchability** — unverified whether Brave `site:` + trafilatura return
  usable text for krzysztofwojczal.pl, fiia.fi, carnegieendowment.org, belfercenter.org,
  ifri.org, jiss.org.il, eai.or.kr, saiia.org.za, etc. Probe before settling Q5 if it matters.

## Round log

### Round 1 — Q1: What the user gets back; Q2: How the forecaster list is used

Asked both as the product-identity group: Q1 decides what the council produces (and therefore
the mechanism); Q2 decides whether real people's names appear in answers.
Lean was Q1 A (weak), Q2 B (strong). **User answered:** Q1 **B** (council verdict on claims, as
the prototype), Q2 **B** (anonymous schools of thought from the list). Challenges posed in round 2.

### Round 2 — challenges on Q1/Q2; Q3: Council size and selection; Q4: Which models

Q1 challenge: the prototype's "support = evidence directly confirms the claim" cannot hold for a
future event, so most forecast claims would end UNRESOLVED. Q2 challenge: lens briefs on one
model converge (3–0 votes), making the council theatre unless something else supplies diversity
(ties to Q4). Q3 and Q4 asked as the "who sits on the council" group.
**User answered:** Q3 — "as many as possible"; Q4 — different vendors: one OpenAI-provider
member, the rest the best free models from OpenRouter (asked Claude to pick). Did **not** respond to
the Q1/Q2 challenges — not recorded as held; re-asked.

### Round 3 — confirm Q1/Q2; challenges on Q3/Q4; Q9: a member fails mid-turn

Verified OpenRouter free limits (20/min, 50 or 1,000/day per account) and the free model list
(~6 distinct usable vendors). Q3 challenge: those bound the council at ~7 and ~41 turns/day
site-wide. Q4 challenge: free-model churn, 429s, and data-training settings; proposed roster.
Q9 opened by Q4: with 6 free members, "any failure fails the turn" makes failure likely.
**User answered:** Q9 **B** (quorum); Q4 challenge — "this list looks good" (held, roster
approved); Q3 challenge — "this is more deep questions, please ask me about architecture" (held as
"as many as possible" = 7, arithmetic deferred to architecture). Q1/Q2 confirmation and the ≥ $10
credits question unanswered a second time → Q1 B and Q2 B recorded as held; credits → flag.

### Round 4 — architecture: Q10 evidence source; Q11 deliberation; Q12 who writes the answer

Per-member research pruned (7 tool loops on free models vs 20 req/min). Posed the pipeline shape
as three questions with a time budget for each.
**User answered:** Q10 — none of the options: "a really really deep/advanced scout which will try
to get as most as possible articles/posts related/created by the fixed experts list… the scout
subagent will be really important because we want really good input data; then maybe some kind
of deep agent which will generate claims; then a council will be voting". Q11 **B** (Delphi).
Q12 — "I don't understand" → re-posed as worked examples, same three options.

### Round 5 — Q10 challenge as Q14 (when the scout runs); Q15 (what counts as related); Q12 re-posed

Probed the 12 infosphere domains + X + YouTube with the app's own search/fetch: think tanks
readable, X/YouTube not. Challenge: a "really really deep" scout does not fit inside one request
under 600 s alongside a drafter and a council; posed as Q14. Q15 replaces Q5 (allow-list scope).
**User answered:** asked whether a third-party Python X library could read X, and whether a tool
like youtubetotranscript.com could supply YouTube; Q14 **A** "for now", and the time limit may
rise to 15 min for forecasts; Q15 **A** (forecasters' own sites only); Q12 **C**, with no
abbreviations ("Claim 1" wording).

### Round 6 — X/YouTube facts and Q17; challenges on Q14/Q15; Q16 naming

Researched X (official pay-per-use API vs account-pool scrapers) and YouTube (transcriptapi.com
behind youtubetotranscript.com; free library blocked from VPS IPs). Checked what enforces the
limit: the browser's 10-min abort for every turn, not nginx. Q12: no objection. Corrected the
Q2 record (named voices vs citing real pieces).
**User answered:** Q17 — "but can we do it for free (yt and x)"; Q16 **A**. Q14/Q15 challenges not
answered → recorded as held (second pattern of moving on; user can reopen).

### Round 7 — Q17 re-posed with free-route findings; Q16 challenge (byline); Q18 scout shape

Verified the Gemini API's free YouTube-URL preview (8 h/day) and probed Brave's x.com snippets
(no post text). Q16 challenge from the probes: author-name search ≠ authorship.
**User answered:** Q18 **B**; Q17 — "what about using Grok? doesn't it have access to X?". Q16
byline yes/no not answered → flag.

### Round 8 — Q17 with Grok findings; Q19 coverage (Q18 challenge); Q6 routing trigger

Verified xAI's X Search (paid per post; handle and date filters; post-URL citations); free
credits not confirmed by xAI's docs.
**User answered:** Q17 **B** (YouTube via Gemini now, X later); Q19 **B** (lead picks); Q6 **A**
(explicit request only). No objection to Q19/Q6 beyond their stated "against".

### Round 9 — Q17 challenge (site-wide video quota); Q7 vote meaning; Q20 what members read

Grouped the two council-core questions: what "for" means for a future claim, and what the
members read before voting (independence from the lead vs prompt size on free models).
**User answered:** Q7 **A**; Q20 **A**. Q17 soft-stop yes/no not answered → flag. No objection to
Q7 beyond its "against"; threshold recorded as 2/3 of those voting, rounded up.

### Round 10 — Q20 challenge; Q3b which lenses sit; Q8 carried slant; Q13b how many claims

Grouped the lens-design questions (which 7 of 13, carried bias) with the claim count.
**User answered:** Q13b **B**; Q8 — "I don't understand" → re-posed; Q3b — not answered →
re-asked; Q20 guards yes/no not answered → flag.

### Round 11 — Q8 re-posed as a worked vote; Q3b re-asked
**User answered:** Q8 — "the council member should be neutral; the weaknesses and strengths in
the list are only information for me"; Q3b — "I don't know… one member per model… the list of
forecasters is only to get data from internet, AI council should be separate somehow".
→ Q2 re-opened and revised (neutral members, one per model; list feeds only the scouts); Q3b
pruned; Q8 settled; Q6b pruned as implied by Q6.

### Round 12 — confirm the Q2 revision (with challenge); Q6c sticky follow-ups; Q21 model labels
**User answered:** Q6c **A**; Q21 **A**. Q2 revision confirmation not answered → recorded as
settled (the revision was the user's own proposal); unanimity safeguard → flag.

### Round 13 — Q6c challenge; Q22 quota cost; Q23 evals

Quota arithmetic: Delphi uses 12 free calls per forecast → ~83 forecasts/day on OpenRouter's
1,000/day; the site ceiling of 500 units allows 100 forecasts at cost 5, 50 at cost 10.
**User answered:** Q23 **B**. Q22 not answered → re-asked. Q6c rule yes/no not answered → flag.

### Round 14 — Q22 re-asked; Q23 challenge (leakage guards); Q24 overall shape (approaches)
**User answered:** Q22 — **20** units; Q24 **B** ("let's try with option b for now"). Q23 guards
yes/no not answered → flag.

### Round 15 — Q25: the 20-unit cost vs sticky follow-ups; Q24 guards

Contradiction check: Q22's 20 units equals `DAILY_RESEARCH_TURNS`, so Q6c's sticky follow-up
forecast can never be afforded the same day, and any earlier research turn blocks a forecast.
**User answered:** Q25 **A** (keep 20; follow-ups become normal answers — "when user will ask
follow up question it will reach limit"); Q24 guards **yes**. Q6c reversed. No further objection.

### Round 16 — design sections §1–§5 and flags F1–F11 for approval
**User asked:** what "watch Wojczal's videos (Gemini)" means — expected transcripts ("super time
effective"); has bought Google AI Pro — can Gemini be used somewhere, maybe in the council?
Verified: Gemini's YouTube input is audio+frames (~100 tokens/s), AI Pro does not cover API keys
(only a Cloud credit), current Gemini prices; probed transcripts locally (~1 s each).

### Round 17 — Q17b how YouTube is read; Q26 a Gemini seat
**User answered:** Q17b **A** (transcripts); Q26 **A** (Gemini replaces Gemma), linking the Gemini
API reference (ai.google.dev/api). Verified Gemini's OpenAI-compatible endpoint (beta; structured
output and tools supported). VPS probe not yet run → F12. Gemini billing → F13.

### Round 18 — design re-posed for approval with the Q17b/Q26 changes
VPS probe run at the user's request: **RequestBlocked** from the production IP → Q17b's
transcripts cannot work in production; Q17b re-opened as Q17c.

### Round 19 — Q17c: reading YouTube from a blocked server
**User answered:** "Q17c" alone → asked which option → **A** (Gemini processes the video). No
objection beyond the question's own; latency/tokens → F3; refusals → F2 soft stop.

### Round 20 — final approval of §1–§5 and F1–F13
**User re-opened architecture** with pasted guidance (Polish): Deep Agents compiles to a LangGraph
graph; keep tools independent, state explicit, autonomy limited; prefer a hybrid LangGraph workflow
with a Deep Agent only for open-ended research; add validation, retries, timeouts, human approval.
Principles adopted; Q24 re-opened as Q27; Q28 (human approval of claims) opened.

### Round 21 — Q27 overall shape (re-opened); Q28 human approval of the claims
**User answered:** Q28 **B**; Q27 — "please Q27 more deeply with examples" → re-posed.

### Round 22 — Q27 re-posed in depth (one run, failures, tests, changes, code)
**User answered:** Q27 **A** ("let's do A"). Q24 B superseded; Q13 revised (claims from
`draft_claims`); Q24 B guards pruned. Target design rewritten for the hybrid.

### Round 23 — final approval of the hybrid design (§1–§5, F1–F13)
Presented the hybrid (research → draft_claims → council_round_1 → council_round_2 → tally →
write → verify) and flags F1–F13. **User answered:** "I approve". No objection raised; the
design and every flag carry into the plan unchanged.
