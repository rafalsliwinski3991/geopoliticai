"""Orchestrator judges: routing, the standalone rewrite, and chat answers."""

from __future__ import annotations

from typing import Any

from evals.helpers.judge import Judge, markdown_link_urls

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
CHAT_ANSWER_PROMPT = """
You grade a conversational assistant's answer to a turn that is not a
geopolitical research question.

Conversation:
{conversation}

Actual answer:
{actual}

Expected answer:
{expected}

The answer should respond to the last turn at a length it deserves (a greeting
gets a sentence), cite nothing, and present no invented facts. Wording may
differ from the expected answer.

Choose exactly one label:
1: missing, off-topic, or presents invented facts.
2: responds, but misreads the turn or is badly mis-sized.
3: acceptable, with a noticeable gap in helpfulness or length.
4: matches the expected answer with a small difference.
5: as good as the expected answer.

Give a concise evidence-based explanation.
"""


def _conversation(input: dict[str, Any]) -> str:
    return "\n".join(
        f"{message['type']}: {message['data']['content']}"
        for message in input["messages"]
    )


def _routing_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {"actual": output.get("destination"), "expected": expected["destination"]}


def _query_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    # Only the expert reads `standalone_query`; elsewhere the app discards it.
    if expected["destination"] != "geopolitical":
        return None
    return {
        "conversation": _conversation(input),
        "actual": output.get("standalone_query") or "",
        "expected": expected["standalone_query"],
    }


def _chat_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    if expected["destination"] != "other":
        return None
    return {
        "conversation": _conversation(input),
        "actual": output.get("answer") or "",
        "expected": expected["answer"],
    }


def routing_correct(variables: dict[str, Any]) -> bool:
    """Pass when the turn went where the example expects."""
    return bool(variables["actual"] == variables["expected"])


def chat_no_links(variables: dict[str, Any]) -> bool:
    """Pass when a chat answer cites nothing (chat prompt rule 1)."""
    return bool(variables["actual"]) and not markdown_link_urls(variables["actual"])


def judges() -> tuple[Judge, ...]:
    """Return the orchestrator eval's judges."""
    return (
        Judge("routing_correct", "binary", _routing_view, check=routing_correct),
        Judge("query_matches_expected", "numeric", _query_view, prompt=QUERY_PROMPT),
        Judge("chat_no_links", "binary", _chat_view, check=chat_no_links),
        Judge(
            "chat_answer_matches_expected",
            "numeric",
            _chat_view,
            prompt=CHAT_ANSWER_PROMPT,
        ),
    )
