"""deep_expert_fixed judges: the expert's three on the deep answer, plus depth.

With one key vocabulary the deep eval's answer is `answer`, so the expert_fixed
judges read it unchanged. The fourth, `deeper_than_expert`, compares it with
`baseline_answer`, which the expert writes live from the same recorded pages.
"""

from __future__ import annotations

import re
from typing import Any

from evals.helpers.judge import Judge
from evals.judges.expert_fixed import judges as expert_judges

EXPECTED_KEYS = frozenset({"answer"})
PREAMBLE_OPENING = re.compile(r"^[#*\s]*(plan and scope|scope(,| and) )", re.IGNORECASE)
INSTRUCTION_LEAK = re.compile(
    r"\b(the assignment|assignment's|my instructions|the rules (above|require|i was given))\b",
    re.IGNORECASE,
)
CLOSING_OFFER = re.compile(
    r"\b(would you like|do you want|tell me which|i can (compile|produce|prepare|retrieve|fetch))\b",
    re.IGNORECASE,
)
DEPTH_PROMPT = """
You compare two research answers to the same question, written from the same sources.

Question:
{question}

Deep answer:
{deep_answer}

Expert answer:
{answer}

The deep answer was asked for an in-depth analysis. Judge whether it covers more
of what the sources support: more actors and their positions, causes,
disagreements, and implications, without padding or unsupported claims.

Choose exactly one label:
1: the deep answer is missing, or covers less than the expert answer.
2: about the same coverage as the expert answer.
3: somewhat deeper: one angle the expert answer lacks.
4: clearly deeper: several angles the expert answer lacks.
5: substantially deeper on every angle the sources support.

Give a concise evidence-based explanation naming the angles the deep answer adds.
"""


def _depth_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    # The expert baseline is written by this eval before the judges run. A
    # missing one must fail loudly, not become "", or any nonempty deep answer
    # wins on depth by default.
    baseline = output.get("baseline_answer")
    if not baseline:
        raise KeyError(
            "output.baseline_answer (the expert's live baseline) is required by "
            "the deeper_than_expert judge"
        )
    return {
        "question": input["query"],
        "deep_answer": output.get("answer") or "",
        "answer": baseline,
    }


def _answer_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {"answer": output.get("answer") or ""}


def answer_without_preamble(variables: dict[str, Any]) -> bool:
    """Pass when the answer opens with substance and never quotes its own rules."""
    answer = variables["answer"].strip()
    first_line = answer.splitlines()[0] if answer else ""
    return (
        bool(answer)
        and not PREAMBLE_OPENING.match(first_line)
        and not INSTRUCTION_LEAK.search(answer)
    )


def answer_without_closing_offer(variables: dict[str, Any]) -> bool:
    """Pass when the answer's last paragraph is analysis, not an offer or a question."""
    paragraphs = [p for p in variables["answer"].split("\n\n") if p.strip()]
    return bool(paragraphs) and not CLOSING_OFFER.search(paragraphs[-1])


def judges() -> tuple[Judge, ...]:
    """Return the deep_expert_fixed eval's judges."""
    return (
        *expert_judges(),
        Judge(
            "answer_without_preamble",
            "binary",
            _answer_view,
            check=answer_without_preamble,
        ),
        Judge(
            "answer_without_closing_offer",
            "binary",
            _answer_view,
            check=answer_without_closing_offer,
        ),
        Judge("deeper_than_expert", "numeric", _depth_view, prompt=DEPTH_PROMPT),
    )
