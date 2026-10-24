"""deep_expert_live judges: the live expert's four on the deep answer, plus depth on the same pages."""

from __future__ import annotations

from dataclasses import replace

from evals.helpers.judge import Judge
from evals.judges.deep_expert_fixed import judges as fixed_judges
from evals.judges.expert_live import judges as expert_live_judges
from evals.judges.shared import skip_unless_finished

EXPECTED_KEYS: frozenset[str] = frozenset()
NAMES_AFTER_THE_EXPERTS = (
    "answer_without_preamble",
    "answer_without_closing_offer",
    "deeper_than_expert",
)


def judges() -> tuple[Judge, ...]:
    """Return the deep_expert_live eval's judges."""
    by_name = {judge.name: judge for judge in fixed_judges()}
    return (
        *expert_live_judges(),
        *(
            replace(by_name[name], view=skip_unless_finished(by_name[name].view))
            for name in NAMES_AFTER_THE_EXPERTS
        ),
    )
