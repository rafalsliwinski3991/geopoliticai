"""Unit tests for `evals.judges.e2e_orchestrator` code checks and views."""

from __future__ import annotations

from typing import Any

from evals.judges.e2e_orchestrator import (
    _turns_view,
    _without_outlines,
    judges,
    turns_handled,
)


def _turn(
    destination: str | None = None,
    resume_action: str | None = None,
    pause: dict[str, Any] | None = None,
) -> dict[str, Any]:
    turn: dict[str, Any] = {}
    if destination is not None:
        turn["destination"] = destination
    if resume_action is not None:
        turn["resume_action"] = resume_action
    if pause is not None:
        turn["pause"] = pause
    return turn


def test_turns_handled_passes_on_matching_turns() -> None:
    # Arrange
    variables = {
        "actual": [_turn(destination="geopolitical"), _turn(resume_action="revise")],
        "expected": [_turn(destination="geopolitical"), _turn(resume_action="revise")],
    }

    # Act + Assert
    assert turns_handled(variables)


def test_turns_handled_fails_on_different_length() -> None:
    # Arrange
    variables = {"actual": [_turn(destination="other")], "expected": []}

    # Act + Assert
    assert not turns_handled(variables)


def test_turns_handled_fails_on_different_destination() -> None:
    # Arrange
    variables = {
        "actual": [_turn(destination="other")],
        "expected": [_turn(destination="report")],
    }

    # Act + Assert
    assert not turns_handled(variables)


def test_turns_handled_fails_on_different_resume_action() -> None:
    # Arrange
    variables = {
        "actual": [_turn(resume_action="cancel")],
        "expected": [_turn(resume_action="revise")],
    }

    # Act + Assert
    assert not turns_handled(variables)


def test_turns_handled_fails_when_pause_on_one_side_only() -> None:
    # Arrange
    variables = {
        "actual": [_turn(destination="report", pause={"outline": ["A"]})],
        "expected": [_turn(destination="report")],
    }

    # Act + Assert
    assert not turns_handled(variables)


def test_without_outlines_replaces_pause_dict_with_true() -> None:
    # Arrange
    turns = [
        _turn(destination="geopolitical"),
        _turn(resume_action="revise", pause={"outline": ["A"], "notice": ""}),
    ]

    # Act
    result = _without_outlines(turns)

    # Assert
    assert result[0] == turns[0]
    assert result[1]["pause"] is True
    assert result[1]["resume_action"] == "revise"


def test_turns_view_builds_variables() -> None:
    # Arrange
    expected = [_turn(destination="report")]

    # Act
    variables = _turns_view(
        input={}, output={"turns": expected}, expected={"turns": expected}
    )

    # Assert
    assert variables["actual"] == expected
    assert variables["expected"] == expected


def test_judges_have_unique_names() -> None:
    # Act
    names = [judge.name for judge in judges()]

    # Assert
    assert len(names) == len(set(names))
