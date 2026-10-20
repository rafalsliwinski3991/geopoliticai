"""Unit tests for `agents.deep_forecaster.models`."""

from typing import Any

import pytest
from pydantic import ValidationError

from agents.deep_forecaster.models import Vote


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            {"claim": 1, "stance": "unsure", "reason": "The sources are too thin."},
            id="missing",
        ),
        pytest.param(
            {
                "claim": 1,
                "stance": "unsure",
                "reason": "The sources are too thin.",
                "evidence": None,
            },
            id="null",
        ),
    ],
)
def test_an_unsure_vote_without_evidence_cites_no_source(
    payload: dict[str, Any],
) -> None:
    """The Anthropic seat left `evidence` out of `unsure` votes in 3 of 4
    round-1s on the 2026-10-14 roster and pydantic refused the whole ballot: a
    missing or null `evidence` on an `unsure` vote is read as citing none."""
    # Act
    vote = Vote.model_validate(payload)
    # Assert
    assert vote.evidence == []


def test_a_for_vote_without_evidence_is_still_malformed() -> None:
    """Only an `unsure` vote may leave `evidence` out: the schema still requires
    it for 'for' and 'against', so no seat is invited to drop it (plan review,
    brainstorm 2026Oct19 Q1)."""
    # Act + Assert
    with pytest.raises(ValidationError):
        Vote.model_validate({"claim": 1, "stance": "for", "reason": "Because."})


def test_the_vote_schema_still_requires_evidence() -> None:
    """The leniency lives in the validator, never in the schema: `evidence`
    stays a required field, so a dropped `evidence` on a 'for' or 'against'
    vote is refused, not read as none."""
    # Assert
    assert "evidence" in Vote.model_json_schema()["required"]
