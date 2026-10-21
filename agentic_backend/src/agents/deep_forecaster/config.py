"""Deep forecaster's own hardcoded config.

Same rule as `agents/expert/config.py`: edited here directly, passed
explicitly, never read from the environment. Whose writing the scouts read is
editorial data in `consts/forecasters.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import LLMSettings

# The research lead and its scouts: the deep expert's model and effort, for its
# reason (a self-driven tool loop, where per-turn latency is the budget; see
# `agents/deep_expert/config.py`). gpt-5* accepts only temperature 1.0.
RESEARCH_LLM_SETTINGS = LLMSettings(
    model="gpt-5-mini",
    temperature=1.0,
    timeout_seconds=120.0,
    max_output_tokens=16_384,
    reasoning_effort="low",
)

# Drafting the claims: one structured call over every source (brainstorm Q27).
# Its output is a few short claims, each with up to six paragraph numbers;
# choosing the paragraphs is why it gets 120 s, not 90 (user decision
# 2026-10-01). The timeout equals `LIMITS.claims_seconds`.
CLAIMS_LLM_SETTINGS = LLMSettings(
    model="gpt-5-mini",
    temperature=1.0,
    timeout_seconds=120.0,
    max_output_tokens=8_192,
    reasoning_effort="low",
)

# The analysis the reader sees, from the claims, the tally and every source.
WRITE_LLM_SETTINGS = LLMSettings(
    model="gpt-5-mini",
    temperature=1.0,
    timeout_seconds=150.0,
    max_output_tokens=16_384,
    reasoning_effort="low",
)
# A ballot is short, but the reasoning members spend output tokens thinking.
MEMBER_MAX_OUTPUT_TOKENS = 8_192


@dataclass(frozen=True)
class Seat:
    """One council seat's model, an OpenRouter slug (brainstorm Q4, Q26).

    Every seat is a paid model on OpenRouter (user decisions 2026-10-08 and
    2026-10-14): the free tier's shared pool and its churn — retired `:free`
    slugs returning 404, upstream-provider 429s — broke round-1 quorum twice
    in the first smoke week.
    """

    model: str
    reasoning_effort: str | None = None


# One seat per vendor (Q3, Q4), all seven on OpenRouter with the one
# `OPENROUTER_API_KEY` (user decision 2026-10-14, replacing the OpenAI-direct
# and Gemini-direct seats). Cheap and current, prices checked 2026-10-14 in $
# per million tokens in/out: luna .10/.50, gemini-3.5-flash-lite .30/2.50,
# haiku-5.5 .10/.50, glm-5.3-flash .04/.90, deepseek-v4.1-flash .02/.89,
# qwen3.8-flash .15/.47, kimi-k2.5 .50/2.50. Every slug lists `tools` and
# `tool_choice`, which the ballots' tool calling needs. Seats 1 and 2 keep
# `reasoning_effort="low"` as before, Qwen runs with thinking off, and the
# others run at their default, as the old OpenRouter seats did. Moonshot
# replaced Mistral (user decision 2026-10-14): `mistral-small-2603` and
# `mistral-large-2512` had only Mistral as a provider, and it returned 429 on
# every attempt. How this roster judges shows in the live
# `deep_forecaster_live` eval and on the `council_member` spans.
# Member n is COUNCIL[n - 1],
# so reordering renumbers members. Roster churn is an edit here (brainstorm
# §5); which model holds which seat, and which one voted, is logged, never
# shown (Q21).
COUNCIL: tuple[Seat, ...] = (
    Seat("openai/gpt-6-luna", reasoning_effort="low"),
    Seat("google/gemini-3.5-flash-lite", reasoning_effort="low"),
    Seat("anthropic/claude-haiku-5.5"),
    Seat("z-ai/glm-5.3-flash"),
    Seat("deepseek/deepseek-v4.1-flash"),
    # Thinking off: in thinking mode Alibaba rejects the forced `tool_choice`
    # every ballot sends (400 on every call, probe 2026-10-14).
    Seat("qwen/qwen3.8-flash", reasoning_effort="none"),
    Seat("moonshotai/kimi-k2.5"),
)


@dataclass(frozen=True)
class VideoSettings:
    """Gemini reading one public YouTube video (brainstorm 2026Sep30 Q17c).

    Static processing, committed after the unit 03 probe (2026-10-01): a
    ~1-hour Wojczal video answered in 12 s at 129,698 prompt tokens — close
    to the fps=0.1 estimate of ~24k frame tokens plus ~115k audio tokens, so
    the custom `fps` is respected. `media_processing` is never sent: the API
    rejects it for a YouTube URL with 400 "mime_type must be set when
    media_processing is specified" (the probe's first attempt). The
    `processing` knob v1..v3 carried is gone; `VideoMetadata` is marked
    deprecated in the current API reference, but the installed SDK has no
    other `fps` path for a YouTube URL.
    """

    model: str = "gemini-3.8-flash"
    fps: float = 0.1
    timeout_seconds: float = 120.0
    max_output_tokens: int = 8_192


@dataclass(frozen=True)
class ForecastLimits:
    """Caps on one forecast (brainstorm 2026Sep30 §3, F3, F7).

    Only `wall_seconds` is a hard error (`ResearchLimitError`, 504). The
    research budgets are messages to the scouts, and `research_seconds` ends
    research with whatever was read (plan decision: the node returns the
    tools' records, never the lead's text, so only unfinished reads are lost).

    The step budgets add up to at least 30 s less than the wall: research
    240 + claims 120 + council round 1 of two 100 s tries + round 2 of one
    100 s try + writing 150 = 810 s, under the 840 s wall, which is under the
    browser's 15-minute abort (`frontend/chat/src/lib/sse.ts`). A member
    whose first answer cannot be counted is asked once more in round 1
    (brainstorm 2026Oct19 Q1); research's box shrank from 330 s to pay for
    it, because scouts that start together finish in 60-162 s (Phoenix,
    brainstorm 2026Oct19). The slack covers the unbudgeted work (building the
    agent, tally, verify, cancelling research), so a forecast whose every
    step uses its whole budget still finishes instead of hitting the wall
    (pinned by `test_config`). The sum describes the first pass only:
    `verify` can send the analysis back to the writer once, and that retry
    runs in whatever time is left before the wall. `member_seconds` bounds
    one try; Kimi's slowest measured answer was 96 s.

    `max_sources` bounds what the claims drafter and the writer read: 40
    pages of at most 20,000 characters is ~200k tokens at ~4 characters per
    token; a denser language at ~3 characters per token reaches ~267k, still
    under gpt-5-mini's 272,000-token input limit (OpenAI, "Introducing GPT-5
    for developers").
    Both caps were doubled so the forecast shows its full potential (user
    decision 2026-10-19); production had used all 24 searches and 15-20 of 20
    pages in every run. Gemini's video notes count as sources. Council
    members read only the paragraphs the drafter
    points at, at most `max_passages` per claim (user decision 2026-10-01,
    overriding Q20's "every member reads everything"): about 10k tokens.
    `claims_seconds` and `write_seconds` are LangGraph node
    timeouts (`graph.STEPS`): `llm.ainvoke_structured` retries, so the
    per-attempt `timeout_seconds` alone would not bound a step. Each equals
    its call's per-attempt timeout, so a slow attempt ends as the node's 504
    and only a fast failure (a quick 429) is retried inside the budget.
    `max_search_concurrency` caps parallel Brave requests across scouts: the
    dev key allows 50 per second (`x-ratelimit-limit`, measured 2026-10-19),
    and the production key allows at least 8 per second (checked 2026-10-20),
    so 8 stays under it.
    `max_batch` caps the queries or URLs one tool call runs, so one scout
    cannot spend the shared budget in a single call. `max_shown_chars` cuts
    each page a batch read shows the scout, so five pages stay under
    deepagents' 80,000-character tool-result eviction threshold
    (`deepagents/middleware/filesystem.py`); the whole page is recorded for
    the drafter and the writer.

    `quorum` is the fewest valid round-1 ballots after the re-asks (4 of 7,
    user decision 2026-10-19, brainstorm 2026Oct19 Q2b); 5 or more is the
    normal council, and the eval reports a council of 4 separately.

    `max_passage_chars` cuts one quoted paragraph, so a member's prompt stays
    near 10k tokens (4 claims x 6 passages x 1,200 characters). Up to 7
    members x 4 claims of reasons, each with its source links, are printed in
    the answer, which the delivery layer clips at 50,000 characters
    (`api.MAX_ANSWER_CHARS`): with `max_reason_chars` and `max_evidences`,
    28 x (600 + 5 links of ~100) is ~31,000.
    """

    max_searches: int = 48
    max_sources: int = 40
    max_videos: int = 2
    max_search_concurrency: int = 8
    max_batch: int = 5
    max_shown_chars: int = 14_000
    research_seconds: float = 240.0
    claims_seconds: float = 120.0
    member_seconds: float = 100.0
    write_seconds: float = 150.0
    quorum: int = 4
    min_claims: int = 2
    max_claims: int = 4
    max_passages: int = 6
    max_passage_chars: int = 1_200
    max_reason_chars: int = 600
    max_evidences: int = 5
    wall_seconds: float = 840.0


VIDEO_SETTINGS = VideoSettings()
LIMITS = ForecastLimits()
