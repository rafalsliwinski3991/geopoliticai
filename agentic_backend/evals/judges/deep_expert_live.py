"""deep_expert_live judges: the live expert's four on the deep answer, plus depth on the same pages."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from evals.helpers.judge import Judge
from evals.judges.deep_expert_fixed import judges as fixed_judges
from evals.judges.expert_live import judges as expert_live_judges
from evals.judges.shared import skip_unless_finished

EXPECTED_KEYS: frozenset[str] = frozenset()
NAMES_BEFORE_GRADER = ("answer_without_preamble", "answer_without_closing_offer")
NAMES_AFTER_GRADER = ("deeper_than_expert",)


def _verdicts_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {"verdicts": list(output.get("grader_verdicts") or [])}


def grader_satisfied(variables: dict[str, Any]) -> bool:
    """Pass when the grader's last verdict was `satisfied`, not the round cap."""
    return bool(variables["verdicts"][-1:] == ["satisfied"])


def judges() -> tuple[Judge, ...]:
    """Return the deep_expert_live eval's judges."""
    by_name = {judge.name: judge for judge in fixed_judges()}
    return (
        *expert_live_judges(),
        *(_gated(by_name[name]) for name in NAMES_BEFORE_GRADER),
        Judge(
            "grader_satisfied",
            "binary",
            skip_unless_finished(_verdicts_view),
            check=grader_satisfied,
        ),
        *(_gated(by_name[name]) for name in NAMES_AFTER_GRADER),
    )


def _gated(judge: Judge) -> Judge:
    return replace(judge, view=skip_unless_finished(judge.view))
