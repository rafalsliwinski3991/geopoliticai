"""Unit tests for `evals.judges.forecast_backtest`."""

from __future__ import annotations

from typing import Any

from evals.judges.forecast_backtest import _leakage_view, _outcome_view, judges


def test_judge_names_are_the_two() -> None:
    # Act
    names = [judge.name for judge in judges()]
    # Assert
    assert names == ["verdicts_match_outcome", "outcome_unknown_without_sources"]


def test_the_outcome_view_reads_expected_outcome_and_the_verdicts() -> None:
    # Arrange
    input: dict[str, Any] = {"query": "q"}
    output: dict[str, Any] = {
        "claims": ["Claim 1: A"],
        "verdicts": ["Claim 1: ACCEPTED"],
    }
    expected: dict[str, Any] = {"outcome": "It happened."}
    # Act
    variables = _outcome_view(input, output, expected)
    # Assert
    assert variables == {
        "question": "q",
        "outcome": "It happened.",
        "claims": "Claim 1: A",
        "verdicts": "Claim 1: ACCEPTED",
    }


def test_the_leakage_view_reads_expected_outcome_and_the_probe() -> None:
    # Arrange
    output: dict[str, Any] = {"leak_probe": "Member 1: I do not know."}
    expected: dict[str, Any] = {"outcome": "It happened."}
    # Act
    variables = _leakage_view({"query": "q"}, output, expected)
    # Assert
    assert variables == {
        "question": "q",
        "outcome": "It happened.",
        "probe": "Member 1: I do not know.",
    }


def test_every_prompt_field_is_supplied() -> None:
    # Arrange
    from evals.judges.forecast_backtest import LEAKAGE_PROMPT, OUTCOME_PROMPT

    outcome_vars = _outcome_view(
        {"query": "q", "focal_claim": 1},
        {"claims": ["Claim 1: C"], "verdicts": ["Claim 1: V"]},
        {"outcome": "O"},
    )
    leakage_vars = _leakage_view({"query": "q"}, {"leak_probe": "P"}, {"outcome": "O"})
    # Act + Assert
    assert outcome_vars is not None and leakage_vars is not None
    assert set(outcome_vars) >= {"question", "outcome", "claims", "verdicts"}
    OUTCOME_PROMPT.format(**outcome_vars)
    assert set(leakage_vars) >= {"question", "outcome", "probe"}
    LEAKAGE_PROMPT.format(**leakage_vars)


def test_only_the_focal_claim_is_scored() -> None:
    # Arrange: a second claim whose outcome the dataset does not know.
    input: dict[str, Any] = {"query": "q", "focal_claim": 1}
    output: dict[str, Any] = {
        "claims": ["Claim 1: A", "Claim 2: B"],
        "verdicts": ["Claim 1: ACCEPTED", "Claim 2: UNRESOLVED"],
    }
    expected: dict[str, Any] = {"outcome": "It happened."}
    # Act
    variables = _outcome_view(input, output, expected)
    # Assert
    assert variables is not None
    assert variables["claims"] == "Claim 1: A"
    assert variables["verdicts"] == "Claim 1: ACCEPTED"


def test_view_returns_none_for_a_missing_or_empty_probe() -> None:
    # Arrange + Act + Assert: neither case may be scored as a pass, and the
    # missing/empty probe makes the judge not applicable.
    assert _leakage_view({"query": "q"}, {}, {"outcome": "O"}) is None
    assert (
        _leakage_view({"query": "q"}, {"leak_probe": "   "}, {"outcome": "O"}) is None
    )


def test_an_outcome_view_without_the_focal_claim_is_not_applicable() -> None:
    # Arrange
    input: dict[str, Any] = {"query": "q", "focal_claim": 3}
    output: dict[str, Any] = {
        "claims": ["Claim 1: A"],
        "verdicts": ["Claim 1: ACCEPTED"],
    }
    expected: dict[str, Any] = {"outcome": "O"}
    # Act + Assert: the score would be a guess; the judge declines instead.
    assert _outcome_view(input, output, expected) is None
