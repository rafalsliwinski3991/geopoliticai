"""Deep expert judges: the expert eval's three, reused on the deep answer, plus depth.

The three come from `evals/judges/expert.py` unchanged: `urls_from_sources`
(every link is a recorded source), `answer_matches_expected` (same substance
as the hand-written expected answer), and `faithful_to_sources` (every claim
is supported by the source it links). They read `answer`, which in this eval
is the expert's own, so each is pointed at `deep_answer` here. The fourth,
`deeper_than_expert`, is this eval's own: it compares `deep_answer` with
`answer`, which the expert writes live from the same recorded sources.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from evals.helpers.judge import Judge, View
from evals.judges.expert import judges as expert_judges

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


def _on_deep_answer(view: View) -> View:
    """Point one of the expert's views at `deep_answer`, which it knows as `answer`."""

    def adapted(
        input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
    ) -> dict[str, Any] | None:
        return view(
            input,
            {"answer": output.get("deep_answer")},
            {"answer": expected["deep_answer"]},
        )

    return adapted


def _depth_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    # The expert baseline is written live by this eval before the judges run
    # (`deep_expert.run_deep_expert`). A missing one must fail loudly, not
    # become "", or any nonempty deep answer wins on depth by default.
    answer = output.get("answer")
    if not answer:
        raise KeyError(
            "output.answer (the expert's live baseline) is required by the "
            "deeper_than_expert judge"
        )
    return {
        "question": input["query"],
        "deep_answer": output.get("deep_answer") or "",
        "answer": answer,
    }


def judges() -> tuple[Judge, ...]:
    """Return the deep expert eval's judges."""
    return (
        *(
            replace(judge, view=_on_deep_answer(judge.view))
            for judge in expert_judges()
        ),
        Judge("deeper_than_expert", "numeric", _depth_view, prompt=DEPTH_PROMPT),
    )
