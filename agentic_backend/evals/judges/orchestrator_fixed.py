"""orchestrator_fixed judges: where the classifier sends a turn, and its standalone rewrite."""

from __future__ import annotations

from typing import Any

from evals.helpers.judge import Judge

EXPECTED_KEYS = frozenset({"destination", "standalone_query"})
QUERY_PROMPT = """
You grade how an assistant rewrote the last user turn of a conversation into a
standalone question.

Conversation:
{conversation}

Actual rewrite:
{actual}

Expected rewrite:
{expected}

A good rewrite resolves pronouns and elisions from the conversation and keeps
the user's meaning without broadening, narrowing, or answering it. Wording may
differ from the expected rewrite; meaning may not.

Choose exactly one label:
1: missing, or a different question.
2: related, but materially broadened, narrowed, or with an unresolved reference.
3: same topic with a noticeable change in scope.
4: same meaning with a small loss of detail.
5: same meaning as the expected rewrite.

Give a concise evidence-based explanation.
"""


def _conversation(input: dict[str, Any]) -> str:
    return "\n".join(
        f"{message['role']}: {message['content']}" for message in input["messages"]
    )


def _routing_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    if "destination" not in expected:
        return None
    return {"actual": output.get("destination"), "expected": expected["destination"]}


def _query_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    # The dataset expects a rewrite only on research routes; elsewhere the app
    # discards it.
    if "standalone_query" not in expected:
        return None
    return {
        "conversation": _conversation(input),
        "actual": output.get("standalone_query") or "",
        "expected": expected["standalone_query"],
    }


def routing_correct(variables: dict[str, Any]) -> bool:
    """Pass when the turn went where the example expects."""
    return bool(variables["actual"] == variables["expected"])


def judges() -> tuple[Judge, ...]:
    """Return the orchestrator_fixed eval's judges."""
    return (
        Judge("routing_correct", "binary", _routing_view, check=routing_correct),
        Judge("query_matches_expected", "numeric", _query_view, prompt=QUERY_PROMPT),
    )
