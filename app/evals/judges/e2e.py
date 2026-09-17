"""e2e judges: per-turn handling, and the conversation against the expected one."""

from __future__ import annotations

import json
from typing import Any

from evals.helpers.judge import Judge

CONVERSATION_PROMPT = """
You grade a multi-turn conversation with a research assistant against the
expected one.

What the user typed, in order:
{turns}

Actual result per turn:
{actual}

Expected result per turn:
{expected}

Each turn records where it was routed, how a reply at a paused report was
understood, whether the report paused for approval, and the answer. Compare
turn by turn; wording may differ, substance may not.

Choose exactly one label:
1: the conversation went a different way.
2: several turns differ in substance.
3: one turn differs in substance.
4: every turn matches with a small loss of detail.
5: every turn matches the expected conversation.

Give a concise evidence-based explanation naming the turn that differs.
"""


def _without_outlines(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep that a turn paused, not the outline: the reporter samples at temperature 1.0."""
    return [
        {**turn, "pause": True} if "pause" in turn else dict(turn) for turn in turns
    ]


def _turns_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {"actual": list(output.get("turns") or []), "expected": expected["turns"]}


def _conversation_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {
        "turns": "\n".join(
            f"{number}. {turn['text']}" for number, turn in enumerate(input["turns"], 1)
        ),
        "actual": json.dumps(_without_outlines(output.get("turns") or []), indent=2),
        "expected": json.dumps(_without_outlines(expected["turns"]), indent=2),
    }


def turns_handled(variables: dict[str, Any]) -> bool:
    """Pass when every turn routed, classified, and paused as expected."""
    actual, expected = variables["actual"], variables["expected"]
    return len(actual) == len(expected) and all(
        got.get("destination") == want.get("destination")
        and got.get("resume_action") == want.get("resume_action")
        and ("pause" in got) == ("pause" in want)
        for got, want in zip(actual, expected, strict=True)
    )


def judges() -> tuple[Judge, ...]:
    """Return the e2e eval's judges."""
    return (
        Judge("turns_handled", "binary", _turns_view, check=turns_handled),
        Judge(
            "conversation_matches_expected",
            "numeric",
            _conversation_view,
            prompt=CONVERSATION_PROMPT,
        ),
    )
