"""Live deep-forecaster e2e judges: shape and self-consistency, no references."""

from __future__ import annotations

from typing import Any

from evals.helpers.judge import Judge
from evals.judges.deep_forecaster import (
    CLAIMS_PROMPT,
    TALLY_PROMPT,
    _claims_view,
    _tally_view,
)


def judges() -> tuple[Judge, ...]:
    """Return the live run's judges: shape and self-consistency only.

    The expert's two source judges need recorded sources to compare against;
    a live run has none (see `evals/e2e_deep_forecaster.py`), so they are
    deliberately absent.
    """
    return (
        Judge("claims_checkable", "binary", _claims_view, prompt=CLAIMS_PROMPT),
        Judge("prose_matches_tally", "binary", _tally_view, prompt=TALLY_PROMPT),
    )


def not_applicable(input: dict[str, Any], output: dict[str, Any]) -> str | None:
    """A dataset-consistency note the live dataset's empty references need."""
    return None
