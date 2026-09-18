"""Orchestrator agent's own hardcoded config.

Same rule as `agents/expert/config.py`: edited here directly, passed
explicitly into node calls, never read from the environment.
"""

from __future__ import annotations

from config import LLMSettings

# Routing is a short, cheap, deterministic call: a small token ceiling and a
# short timeout, because the user is waiting on it before anything else runs.
CLASSIFY_LLM_SETTINGS = LLMSettings(
    model="gpt-4o-mini",
    temperature=0.0,
    timeout_seconds=20.0,
    max_output_tokens=512,
)

# The general-assistant branch. Smaller ceiling than the expert's 16_384: a
# sourceless chat answer that runs to sixteen thousand tokens is a bug, not a
# feature.
CHAT_LLM_SETTINGS = LLMSettings(
    model="gpt-4o-mini",
    temperature=0.0,
    timeout_seconds=60.0,
    max_output_tokens=4_096,
)

# One turn is one user message plus the assistant reply it drew. Counting
# turns bounds the number of exchanges, not their size: a single expert answer
# may run to `ANSWER_LLM_SETTINGS.max_output_tokens`, so ten turns can still be
# a very large payload. This is a cheap bound, deliberately, not a cost budget
# (brainstorm Q14 — accepted risk).
HISTORY_WINDOW_TURNS = 10
HISTORY_WINDOW_MESSAGES = HISTORY_WINDOW_TURNS * 2
