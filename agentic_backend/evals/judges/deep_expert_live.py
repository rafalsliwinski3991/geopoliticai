"""deep_expert_live judges: the live expert's four on the deep answer, plus depth on the same pages."""

from __future__ import annotations

from dataclasses import replace

from evals.helpers.judge import Judge
from evals.judges.deep_expert_fixed import judges as fixed_judges
from evals.judges.expert_live import judges as expert_live_judges
from evals.judges.shared import skip_unless_finished

EXPECTED_KEYS: frozenset[str] = frozenset()


def judges() -> tuple[Judge, ...]:
    """Return the deep_expert_live eval's judges."""
    depth = next(
        judge for judge in fixed_judges() if judge.name == "deeper_than_expert"
    )
    return (
        *expert_live_judges(),
        replace(depth, view=skip_unless_finished(depth.view)),
    )
