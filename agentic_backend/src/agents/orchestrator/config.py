"""Orchestrator agent's own hardcoded config.

Same rule as `agents/expert/config.py`: edited here directly, passed
explicitly into node calls, never read from the environment.
"""

from __future__ import annotations

from config import LLMSettings

SUPERVISOR_LLM_SETTINGS: LLMSettings = LLMSettings(
    model="gpt-5-mini",
    temperature=0.0,
)

FOOTER_LLM_SETTINGS: LLMSettings = LLMSettings(
    model="gpt-5-mini",
    temperature=0.0,
    max_output_tokens=250,
)

# One turn is one user message plus the assistant reply it drew. Counting
# turns bounds the number of exchanges, not their size: a single expert answer
# may run to `ANSWER_LLM_SETTINGS.max_output_tokens`, so ten turns can still be
# a very large payload. This is a cheap bound, deliberately, not a cost budget
# (brainstorm Q14 — accepted risk).
HISTORY_WINDOW_TURNS = 10
HISTORY_WINDOW_MESSAGES = HISTORY_WINDOW_TURNS * 2
