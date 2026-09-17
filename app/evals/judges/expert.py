"""Expert judges: URL provenance, agreement with the expected answer, faithfulness."""

from __future__ import annotations

from typing import Any

from evals.helpers.judge import Judge, markdown_link_urls

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
FAITHFUL_PROMPT = """
You check whether a research answer is supported by the sources it cites.

Answer:
{answer}

Cited sources:
{sources}

Every factual sentence must be supported by the source its link points to.
Background knowledge that is not in the cited source text counts as unsupported.

Choose exactly one label:
1: most claims are unsupported or contradicted.
2: several claims are unsupported.
3: one material claim is unsupported.
4: all material claims are supported; a minor detail is not.
5: every claim is supported by its cited source.

Give a concise evidence-based explanation naming any unsupported claim.
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
    cited = set(markdown_link_urls(answer))
    sources = "\n\n".join(
        f"SOURCE {source['url']}\n{source['title']}\n{source['text']}"
        for source in input["sources"]
        if source["url"] in cited
    )
    return {
        "answer": answer,
        "sources": sources or "(the answer cites no recorded source)",
    }


def urls_from_sources(variables: dict[str, Any]) -> bool:
    """Pass when the answer links, and only to recorded sources (expert rule 1)."""
    urls = markdown_link_urls(variables["answer"])
    return bool(urls) and set(urls) <= set(variables["source_urls"])


def judges() -> tuple[Judge, ...]:
    """Return the expert eval's judges."""
    return (
        Judge("urls_from_sources", "binary", _urls_view, check=urls_from_sources),
        Judge("answer_matches_expected", "numeric", _answer_view, prompt=ANSWER_PROMPT),
        Judge("faithful_to_sources", "numeric", _faithful_view, prompt=FAITHFUL_PROMPT),
    )
