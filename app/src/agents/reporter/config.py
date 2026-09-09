"""Reporter agent's own hardcoded config.

Same rule as `agents/expert/config.py` and `agents/orchestrator/config.py`:
edited here directly, passed explicitly into node calls, never read from the
environment.
"""

from __future__ import annotations

from config import LLMSettings

# The outline reads the whole thread (brainstorm Q15), so it needs the large
# window. `gpt-5-mini` supports `with_structured_output(..., method="json_schema",
# strict=True)`, verified through this repo's own `llm.py` boundary. Its context
# window (~400k tokens) is an OpenAI-published figure, not something measurable
# from any installed package — see §1's "unverified provider claims".
OUTLINE_LLM_SETTINGS = LLMSettings(
    model="gpt-5-mini",
    # 1.0, not 0.0. `gpt-5*` non-chat models accept only temperature 1, and
    # langchain-openai 0.3.35 *silently drops* any other value before the
    # request is built (`chat_models/base.py:720-744`, `validate_temperature`).
    # Measured through this repo's own `llm._build_client`: gpt-5-mini at 0.0
    # yields `temperature=None` and no temperature in the payload, while
    # gpt-4o-mini keeps 0.0. Writing 1.0 makes the code say what actually
    # happens. Outline generation is therefore NOT deterministic.
    temperature=1.0,
    timeout_seconds=120.0,
    max_output_tokens=8_192,
)

# The report itself. On a reasoning model `max_output_tokens` is understood to
# cover reasoning *and* visible tokens, so this is sized for both; gpt-5-mini's
# published ceiling is 128_000. Both of those are OpenAI-documented claims, not
# local measurements (§1). The timeout is far above the 60s default because a
# long synthesis is slow; nginx allows 600s and the browser aborts at 600s, so
# 300s fits inside both with room to report the failure.
REPORT_LLM_SETTINGS = LLMSettings(
    model="gpt-5-mini",
    temperature=1.0,  # see OUTLINE_LLM_SETTINGS: 0.0 is silently dropped
    timeout_seconds=300.0,
    max_output_tokens=32_768,
)

# Sorting one typed line while the thread is paused. Same shape as the
# orchestrator's classifier: short, cheap, deterministic, user waiting on it.
# gpt-4o-mini is not a gpt-5 model, so temperature 0.0 is genuinely honoured
# here — unlike the two settings above.
INTENT_LLM_SETTINGS = LLMSettings(
    model="gpt-4o-mini",
    temperature=0.0,
    timeout_seconds=20.0,
    max_output_tokens=512,
)

# Newest-first character budget for the transcript. ~400k characters is roughly
# 100k tokens, a quarter of gpt-5-mini's window, leaving room for the prompt and
# the reasoning budget. Truncation is silent by decision (Q7A) and is the real
# safety net now that the reporter reads the whole thread (Q15). The number was
# put to the user and confirmed; the worst case it admits is ~700k input tokens
# for one report driven to the revision cap.
MAX_TRANSCRIPT_CHARS = 400_000

# Ceiling on the report text stored in the conversation. Sized to the delivery
# layer's own cap deliberately: the browser receives at most `MAX_ANSWER_CHARS`
# (50,000) and the download is built from that stream, so a longer report is
# readable by *nobody*. Storing it anyway would only inflate every later
# `classify` and `chat` prompt, which slice the last 20 messages with no
# character budget of their own. Kept here rather than imported from `api.py`:
# an agent must not depend on a delivery-layer constant. If that cap ever
# changes, this must not be looser than it — asserted in `test_api.py`.
MAX_REPORT_CHARS = 50_000

# Each revision round costs exactly one outline call (measured), so per-round
# cost is bounded. Hitting this *ends the run* (see `nodes/outline.py`) rather
# than merely declining to call the model again — a cap that only stops the
# model call leaves the pause unresolvable and `revisions` unbounded (measured).
# Q4 left the cap undecided and the brainstorm flagged it as needing a number.
MAX_REVISION_ROUNDS = 5
