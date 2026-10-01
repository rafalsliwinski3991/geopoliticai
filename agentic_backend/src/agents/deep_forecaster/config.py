"""Deep forecaster's own hardcoded config.

Same rule as `agents/expert/config.py`: edited here directly, passed
explicitly, never read from the environment. Whose writing the scouts read is
editorial data in `consts/forecasters.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
# A ballot is short, but the free reasoning models spend output tokens thinking.
MEMBER_MAX_OUTPUT_TOKENS = 8_192


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
    330 + claims 120 + two council rounds of 100 + writing 150 = 800 s, under
    the 840 s wall, which is under the browser's 15-minute abort
    (`frontend/chat/src/lib/sse.ts`). The slack covers the unbudgeted work
    (building the agent, tally, verify, cancelling research), so a forecast
    whose every step uses its whole budget still finishes instead of hitting
    the wall (pinned by `test_config`). One stalled seat already pins each
    round at `member_seconds`, so the rounds' 200 s is the normal case. The
    budgets are estimates until the smoke runs (F3) measure them.

    `max_sources` bounds what the claims drafter and the writer read: 20
    pages of at most 20,000 characters is ~100k tokens. Gemini's video notes
    count as sources. Council members read only the paragraphs the drafter
    points at, at most `max_passages` per claim (user decision 2026-10-01,
    overriding Q20's "every member reads everything"): about 10k tokens.
    `quorum` is the fewest members whose round-1 ballots make a council (Q9,
    F7). `free_attempt_seconds` is a free seat's own try inside
    `member_seconds`, which leaves its paid fallback at least 45 s
    (`council._cast`). `claims_seconds` and `write_seconds` are LangGraph node
    timeouts (`graph.STEPS`): `llm.ainvoke_structured` retries, so the
    per-attempt `timeout_seconds` alone would not bound a step. Each equals
    its call's per-attempt timeout, so a slow attempt ends as the node's 504
    and only a fast failure (a quick 429) is retried inside the budget.
    `max_search_concurrency` caps parallel Brave requests across scouts; Brave's
    rate limit is unverified.

    `max_passage_chars` cuts one quoted paragraph, so a member's prompt stays
    near 10k tokens (4 claims x 6 passages x 1,200 characters). Up to 7
    members x 4 claims of reasons, each with its source links, are printed in
    the answer, which the delivery layer clips at 50,000 characters
    (`api.MAX_ANSWER_CHARS`): with `max_reason_chars` and `max_evidences`,
    28 x (600 + 5 links of ~100) is ~31,000.
    """

    max_searches: int = 24
    max_sources: int = 20
    max_videos: int = 2
    max_search_concurrency: int = 3
    research_seconds: float = 330.0
    claims_seconds: float = 120.0
    member_seconds: float = 100.0
    free_attempt_seconds: float = 55.0
    write_seconds: float = 150.0
    quorum: int = 5
    min_claims: int = 2
    max_claims: int = 4
    max_passages: int = 6
    max_passage_chars: int = 1_200
    max_reason_chars: int = 600
    max_evidences: int = 5
    wall_seconds: float = 840.0


@dataclass(frozen=True)
class Seat:
    """One council seat's model; `provider` picks its endpoint (brainstorm Q4, Q26).

    `fallback` is a paid OpenRouter model, asked once when the seat's free
    model produces no counted ballot (user decision 2026-10-01, overriding
    Q4's free-only roster for that path; `council._cast`). It is the free
    model's paid twin where OpenRouter lists one, else a model from a vendor
    with no seat, so no vendor ever holds two seats (Q3).
    """

    model: str
    provider: Literal["openai", "gemini", "openrouter"]
    reasoning_effort: str | None = None
    fallback: str | None = None


# One seat per vendor (Q3, Q4, Q26): OpenAI directly, Gemini through its
# OpenAI-compatible endpoint, five free OpenRouter models picked on
# 2026-09-30, each with a paid fallback checked on OpenRouter's public model
# list on 2026-10-01 (all list `tools` and `tool_choice`). dots-3-note-preview
# and ling-3.0-flash-sante have no paid twin: DeepSeek has no seat, and
# ling-3.0-flash is inclusionAI's own base model. poolside is kept out of the
# fallbacks because `poolside/laguna-s-2.1:free` is the named replacement
# seat (plan unit 05 smoke gate). Member n is COUNCIL[n - 1],
# so reordering renumbers members. Roster churn is an edit here (brainstorm
# §5); which model holds which seat, and which one voted, is logged, never
# shown (Q21).
COUNCIL: tuple[Seat, ...] = (
    Seat("gpt-5-mini", "openai", reasoning_effort="low"),
    Seat("gemini-3.8-flash", "gemini", reasoning_effort="low"),
    Seat(
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "openrouter",
        fallback="nvidia/nemotron-3-ultra-550b-a55b",
    ),
    Seat("qwen/qwen3.8-27b:free", "openrouter", fallback="qwen/qwen3.8-27b"),
    Seat(
        "thinkingmachines/inkling:free",
        "openrouter",
        fallback="thinkingmachines/inkling",
    ),
    Seat(
        "dots-studio/dots-3-note-preview:free",
        "openrouter",
        fallback="deepseek/deepseek-v4-flash",
    ),
    Seat(
        "inclusionai/ling-3.0-flash-sante:free",
        "openrouter",
        fallback="inclusionai/ling-3.0-flash",
    ),
)


VIDEO_SETTINGS = VideoSettings()
LIMITS = ForecastLimits()
