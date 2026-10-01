"""Deep expert agent's own hardcoded config.

Same rule as `agents/expert/config.py`: edited here directly, passed
explicitly, never read from the environment. Editorial policy (which outlets)
is the expert's `EXPERT_SOURCES`, imported, not copied.
"""

from __future__ import annotations

from dataclasses import dataclass

from config import LLMSettings

# The planning/searching/writing model. gpt-5* accepts only temperature 1.0;
# see `agents/reporter/config.py` for the measurement. max_output_tokens covers
# reasoning and visible tokens on a reasoning model. `reasoning_effort="low"`
# is the smoke run's measurement (2026-09-29): at the default effort one agent
# turn costs 40-97 s and no useful turn count fits under the deep expert's
# 480 s wall; the deep agent drives its own loop, so per-turn latency is the
# budget.
AGENT_LLM_SETTINGS = LLMSettings(
    model="gpt-5-mini",
    temperature=1.0,
    timeout_seconds=120.0,
    max_output_tokens=16_384,
    reasoning_effort="low",
)

# The RubricMiddleware grader: cheap and deterministic (brainstorm Q10B).
GRADER_LLM_SETTINGS = LLMSettings(
    model="gpt-4o-mini",
    temperature=0.0,
    timeout_seconds=60.0,
    max_output_tokens=4_096,
)


@dataclass(frozen=True)
class ResearchLimits:
    """Caps on one deep turn.

    Only `wall_seconds` is a hard error (`ResearchLimitError`). A spent search
    budget is a message to the model (plan review, user decision), and the
    grader cap ships the last draft (brainstorm Q7A).

    `wall_seconds` must stay well under the browser's 15-minute abort
    (`frontend/chat/src/lib/sse.ts`), leaving room to report the error;
    nginx's 600 s `proxy_read_timeout` bounds only the silence between two
    frames.
    `max_grader_rounds` is RubricMiddleware's `max_iterations`: grader calls,
    so at most `max_grader_rounds - 1` revisions.

    Both caps are smoke-run measurements (2026-09-29): one gpt-5-mini agent
    turn costs ~40-50 s, so the search cap bounds the turn count — 8 searches
    left the draft unwritten at 480 s, and 5 is what a full turn actually
    fits inside against Brave's 1.1 s per search.
    """

    max_searches: int = 5
    max_grader_rounds: int = 3
    wall_seconds: float = 480.0


LIMITS = ResearchLimits()
