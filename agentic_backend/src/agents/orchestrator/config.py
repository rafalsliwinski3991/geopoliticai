"""Orchestrator agent's own hardcoded config.

Same rule as `agents/expert/config.py`: edited here directly, passed
explicitly into node calls, never read from the environment.
"""

from __future__ import annotations

from config import LLMSettings

# gpt-5* accepts only temperature 1.0; langchain-openai drops any other value
# (see `agents/reporter/config.py`), so both settings say 1.0.
# The supervisor also answers chat turns, so it keeps the 4_096-token ceiling
# the retired chat branch had: a sourceless answer of sixteen thousand tokens
# is a bug. Reasoning tokens count against both ceilings on a reasoning model,
# hence `reasoning_effort`.
SUPERVISOR_LLM_SETTINGS: LLMSettings = LLMSettings(
    model="gpt-5-mini",
    temperature=1.0,
    max_output_tokens=4_096,
    reasoning_effort="low",
)

FOOTER_LLM_SETTINGS: LLMSettings = LLMSettings(
    model="gpt-5-mini",
    temperature=1.0,
    max_output_tokens=250,
    reasoning_effort="minimal",
)

# One turn is one user message plus the assistant reply it drew. Counting
# turns bounds the number of exchanges, not their size: a single expert answer
# may run to `ANSWER_LLM_SETTINGS.max_output_tokens`, so ten turns can still be
# a very large payload. This is a cheap bound, deliberately, not a cost budget
# (brainstorm Q14 — accepted risk).
HISTORY_WINDOW_TURNS = 10
HISTORY_WINDOW_MESSAGES = HISTORY_WINDOW_TURNS * 2
