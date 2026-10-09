"""Deep forecaster judges: the expert's two source judges, checkable claims, prose vs vote.

From `evals/judges/expert.py`, unchanged: `urls_from_sources` (the answer
links, and only to recorded sources) and `faithful_to_sources` (every claim is
supported by the source it links). Both read `answer`, which this eval's
output carries. This eval's own:
- `claims_checkable`: every claim names one observable outcome and a deadline.
- `prose_matches_tally`: the writer's prose never describes a claim's vote
  differently from its verdict. `nodes.verify` writes every verdict heading
  from the tally, but the overview is free prose that no code check reads
  (user decision 2026-09-30: measured here, never a runtime 502).
"""

from __future__ import annotations

from typing import Any

from evals.helpers.judge import Judge
from evals.judges.expert import judges as expert_judges

CLAIMS_PROMPT = """
You check the claims a forecasting council voted on.

Question:
{question}

Claims:
{claims}

Each claim must state one concrete, observable outcome and a deadline, so that on
the deadline anyone could tell whether it came true without a judgement call.
Hedged wording ("might", "could", "likely") or a vague outcome fails.

Choose exactly one label:
pass: every claim is checkable in that sense.
fail: at least one claim is not.

Give a concise explanation naming any claim that fails.
"""
TALLY_PROMPT = """
You check a forecast's written analysis against its council's vote.

The council's verdicts, counted by code:
{verdicts}

The answer (analysis first, then the code-written vote list):
{answer}

The analysis must never describe a claim's outcome differently from its
verdict: an UNRESOLVED claim is not called accepted, likely or settled, and an
ACCEPTED or REJECTED claim is not called open or undecided. Ignore the vote
list itself; code wrote it.

Choose exactly one label:
pass: the analysis agrees with every verdict.
fail: the analysis contradicts at least one verdict.

Give a concise explanation naming any claim it contradicts.
"""
REUSED_EXPERT_JUDGES = ("urls_from_sources", "faithful_to_sources")


def _claims_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {"question": input["query"], "claims": "\n".join(output.get("claims") or [])}


def _tally_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {
        "verdicts": "\n".join(output.get("verdicts") or []),
        "answer": output.get("answer") or "",
    }


def judges() -> tuple[Judge, ...]:
    """Return the deep forecaster eval's judges."""
    reused = {judge.name: judge for judge in expert_judges()}
    return (
        *(reused[name] for name in REUSED_EXPERT_JUDGES),
        Judge("claims_checkable", "binary", _claims_view, prompt=CLAIMS_PROMPT),
        Judge("prose_matches_tally", "binary", _tally_view, prompt=TALLY_PROMPT),
    )
