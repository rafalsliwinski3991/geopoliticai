"""Forecast backtest judges: did the verdicts point the right way, and was it knowable?"""

from __future__ import annotations

from typing import Any

from evals.helpers.judge import Judge

OUTCOME_PROMPT = """
You score a forecast against what actually happened.

Question:
{question}

What happened:
{outcome}

The council's claims:
{claims}

Its verdicts:
{verdicts}

An ACCEPTED claim that came true, or a REJECTED claim that did not, points the
right way. The reverse points the wrong way. An UNRESOLVED claim points neither way.

Choose exactly one label:
1: most settled verdicts point the wrong way.
2: the settled verdicts are split between right and wrong.
3: no claim was settled (every claim UNRESOLVED).
4: every settled verdict points the right way, and at least one claim is UNRESOLVED.
5: every claim was settled and points the right way.

Give a concise explanation claim by claim.
"""
LEAKAGE_PROMPT = """
You check whether a model already knew how a question turned out, without sources.

Question:
{question}

What actually happened:
{outcome}

Each council member's reply, given no sources:
{probe}

Choose exactly one label:
pass: no reply states the actual outcome.
fail: any reply states the actual outcome, or enough of it to answer the question.

Give a concise explanation.
"""


def _outcome_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {
        "question": input["query"],
        "outcome": expected["outcome"],
        "claims": "\n".join(output.get("claims") or []),
        "verdicts": "\n".join(output.get("verdicts") or []),
    }


def _leakage_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {
        "question": input["query"],
        "outcome": expected["outcome"],
        "probe": output.get("leak_probe") or "",
    }


def judges() -> tuple[Judge, ...]:
    """Return the backtest's judges."""
    return (
        Judge(
            "verdicts_match_outcome", "numeric", _outcome_view, prompt=OUTCOME_PROMPT
        ),
        Judge(
            "outcome_unknown_without_sources",
            "binary",
            _leakage_view,
            prompt=LEAKAGE_PROMPT,
        ),
    )
