"""expert_live judges: the run finished, links only to pages it read, faithful, on the question."""

from __future__ import annotations

from typing import Any

from evals.helpers.judge import Judge
from evals.judges.shared import (
    FAITHFUL_PROMPT,
    build_outcome_judge,
    render_cited_sources,
    skip_unless_finished,
    urls_from_sources,
)

EXPECTED_KEYS: frozenset[str] = frozenset()
ANSWERS_PROMPT = """
You check whether a research answer answers the question it was asked.

Question:
{question}

Answer:
{answer}

Judge only whether the answer addresses this question: the actors, the event,
and the time it asks about. Do not judge its accuracy or its sources.

Choose exactly one label:
pass: the answer addresses the question asked.
fail: the answer is about something else, or misses the question's core.

Give a concise explanation.
"""


def _urls_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    return {
        "answer": output["answer"],
        "source_urls": [source["url"] for source in output["sources"]],
    }


def _faithful_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    return {
        "answer": output["answer"],
        "sources": render_cited_sources(output["sources"], output["answer"])
        or "(the answer cites no page it read)",
    }


def _answers_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    return {"question": input["query"], "answer": output["answer"]}


def judges() -> tuple[Judge, ...]:
    """Return the expert_live eval's judges."""
    return (
        build_outcome_judge(),
        Judge(
            "urls_from_sources",
            "binary",
            skip_unless_finished(_urls_view),
            check=urls_from_sources,
        ),
        Judge(
            "faithful_to_sources",
            "numeric",
            skip_unless_finished(_faithful_view),
            prompt=FAITHFUL_PROMPT,
        ),
        Judge(
            "answers_the_question",
            "binary",
            skip_unless_finished(_answers_view),
            prompt=ANSWERS_PROMPT,
        ),
    )
