"""deep_expert_fixed judges: the expert's three on the deep answer, plus depth.

With one key vocabulary the deep eval's answer is `answer`, so the expert_fixed
judges read it unchanged. The fourth, `deeper_than_expert`, compares it with
`baseline_answer`, which the expert writes live from the same recorded pages.
"""

from __future__ import annotations

from typing import Any

from evals.helpers.judge import Judge
from evals.judges.expert_fixed import judges as expert_judges

EXPECTED_KEYS = frozenset({"answer"})
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


def judges() -> tuple[Judge, ...]:
    """Return the deep_expert_fixed eval's judges."""
    return (
        *expert_judges(),
        Judge("deeper_than_expert", "numeric", _depth_view, prompt=DEPTH_PROMPT),
    )
