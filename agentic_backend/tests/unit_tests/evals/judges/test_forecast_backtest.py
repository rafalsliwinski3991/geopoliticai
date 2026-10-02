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
        {"query": "q"},
        {"claims": ["C"], "verdicts": ["V"]},
        {"outcome": "O"},
    )
    leakage_vars = _leakage_view({"query": "q"}, {"leak_probe": "P"}, {"outcome": "O"})
    # Act + Assert
    assert set(outcome_vars) >= {"question", "outcome", "claims", "verdicts"}
    OUTCOME_PROMPT.format(**outcome_vars)
    assert set(leakage_vars) >= {"question", "outcome", "probe"}
    LEAKAGE_PROMPT.format(**leakage_vars)
