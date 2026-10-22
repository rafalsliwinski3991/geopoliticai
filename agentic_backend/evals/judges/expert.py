"""Expert judges: URL provenance, agreement with the expected answer, faithfulness."""

from __future__ import annotations

from typing import Any

from evals.helpers.judge import Judge
from evals.judges.shared import FAITHFUL_PROMPT, render_cited_sources, urls_from_sources

ANSWER_PROMPT = """
You grade a research answer written from a fixed set of sources.

Question:
{question}

Actual answer:
{actual}

Expected answer (written from the same sources):
{expected}

Compare facts, conclusions, and how conflicts between sources are attributed.
Wording and structure may differ; substance may not.

Choose exactly one label:
1: missing, or answers a different question.
2: states materially different facts or conclusions.
3: same core answer with a noticeable omission or addition.
4: same substance with a small loss of detail.
5: same substance as the expected answer.

Give a concise evidence-based explanation.
"""


def _urls_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {
        "answer": output.get("answer") or "",
        "source_urls": [source["url"] for source in input["sources"]],
    }


def _answer_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {
        "question": input["query"],
        "actual": output.get("answer") or "",
        "expected": expected["answer"],
    }


def _faithful_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    answer = output.get("answer") or ""
    return {
        "answer": answer,
        "sources": render_cited_sources(input["sources"], answer)
        or "(the answer cites no recorded source)",
    }


def judges() -> tuple[Judge, ...]:
    """Return the expert eval's judges."""
    return (
        Judge("urls_from_sources", "binary", _urls_view, check=urls_from_sources),
        Judge("answer_matches_expected", "numeric", _answer_view, prompt=ANSWER_PROMPT),
        Judge("faithful_to_sources", "numeric", _faithful_view, prompt=FAITHFUL_PROMPT),
    )
