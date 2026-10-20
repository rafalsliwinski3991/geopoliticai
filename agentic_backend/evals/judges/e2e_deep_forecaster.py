"""Live deep-forecaster judges (brainstorm 2026Oct19 Q7, Q8).

Every judge reads the run's own output, never a recording:
- `finished_or_outside` (code): the forecast finished, or failed in a
  provider outage; a failure of our own rules fails the run (Q8).
- `urls_from_sources` (code, the expert's check): the answer links, and only
  to pages this run read. A smoke check: `verify` already guarantees it, so
  it fails only if `verify` regresses.
- `faithful_to_sources`: the expert's prompt over the writer's analysis
  (the vote list's member reasons are judgments) and the full text of the
  pages it cites.
- `claims_checkable`, `prose_matches_tally`: moved from the deleted recorded
  eval, unchanged.
- `verdicts_follow_evidence`: each verdict is a reasonable reading of the
  passages the council read. Consistency, not accuracy: a live question has
  no known outcome (Q7 challenge, B).

A view applies only to a forecast that finished, and decides that from the
actual output: a live dataset has no expected output, and a forecast that
failed outside must not also fail every prose judge (Q8). The dataset's own
empty output applies to no judge.
"""

from __future__ import annotations

from typing import Any

from evals.helpers.judge import Judge
from evals.judges.expert import FAITHFUL_PROMPT, urls_from_sources

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
VERDICTS_PROMPT = """
You check a forecasting council's verdicts against the evidence it read.

Question:
{question}

Each claim, with the passages the council read for it:
{passages}

The council's verdicts, counted by code:
{verdicts}

ACCEPTED means most members judged the claim more likely than not by its
deadline, REJECTED less likely, and UNRESOLVED that the council could not
settle it. A verdict follows the evidence when a careful reader of those
passages alone could reach it. Do not use your own knowledge of the world.

Choose exactly one label:
1: most verdicts contradict their passages.
2: several verdicts do not follow from their passages.
3: one verdict does not follow from its passages.
4: every verdict follows; one is a stretch.
5: every verdict is a reasonable reading of its passages.

Give a concise explanation naming any verdict that does not follow.
"""
OUTSIDE = "outside"


def finished_or_outside(variables: dict[str, Any]) -> bool:
    """Pass a finished forecast, or one a provider outage failed; fail one our rules failed (Q8)."""
    return bool(variables["finished"]) or variables["side"] == OUTSIDE


def _finished(output: dict[str, Any]) -> bool:
    """Return whether the run's forecast finished; an empty output did not."""
    return bool(output.get("finished"))


def _outcome_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    if "finished" not in output:
        return None
    return {"finished": output["finished"], "side": output["side"]}


def _urls_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    if not _finished(output):
        return None
    return {"answer": output["answer"], "source_urls": output["source_urls"]}


def _faithful_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    if not _finished(output):
        return None
    sources = "\n\n".join(
        f"SOURCE {source['url']}\n{source['title']}\n{source['text']}"
        for source in output["cited_sources"]
    )
    return {
        "answer": output["analysis"],
        "sources": sources or "(the analysis cites no source it read)",
    }


def _claims_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    if not _finished(output):
        return None
    return {"question": input["query"], "claims": "\n".join(output["claims"])}


def _tally_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    if not _finished(output):
        return None
    return {"verdicts": "\n".join(output["verdicts"]), "answer": output["answer"]}


def _verdicts_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any] | None:
    if not _finished(output):
        return None
    return {
        "question": input["query"],
        "passages": output["passages"],
        "verdicts": "\n".join(output["verdicts"]),
    }


def judges() -> tuple[Judge, ...]:
    """Return the live forecaster eval's judges."""
    return (
        Judge(
            "finished_or_outside", "binary", _outcome_view, check=finished_or_outside
        ),
        Judge("urls_from_sources", "binary", _urls_view, check=urls_from_sources),
        Judge("faithful_to_sources", "numeric", _faithful_view, prompt=FAITHFUL_PROMPT),
        Judge("claims_checkable", "binary", _claims_view, prompt=CLAIMS_PROMPT),
        Judge("prose_matches_tally", "binary", _tally_view, prompt=TALLY_PROMPT),
        Judge(
            "verdicts_follow_evidence",
            "numeric",
            _verdicts_view,
            prompt=VERDICTS_PROMPT,
        ),
    )
