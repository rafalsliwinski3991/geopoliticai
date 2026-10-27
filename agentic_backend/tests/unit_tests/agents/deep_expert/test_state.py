"""Unit tests for `agents.deep_expert.state`."""

from __future__ import annotations

from typing import Any, cast

from agents.deep_expert.state import ResearchRun
from shared.frames import ProgressFrame


def _evaluation(result: str, iteration: int) -> Any:
    return cast(
        Any,
        {"result": result, "iteration": iteration},
    )


def test_record_evaluation_appends_the_verdict() -> None:
    # Arrange
    events: list[object] = []
    run = ResearchRun(writer=events.append)

    # Act
    run.record_evaluation(_evaluation("satisfied", 0))

    # Assert
    assert run.verdicts == ["satisfied"]
    assert events == []


def test_a_needs_revision_verdict_announces_a_revision() -> None:
    # Arrange
    events: list[object] = []
    run = ResearchRun(writer=events.append)

    # Act
    run.record_evaluation(_evaluation("needs_revision", 0))

    # Assert
    assert run.verdicts == ["needs_revision"]
    assert events == [
        ProgressFrame(node="deep_expert", label="Revising the analysis (1 of 2)...")
    ]


def test_no_announcement_for_a_satisfied_or_crashed_grader() -> None:
    # Arrange
    events: list[object] = []
    run = ResearchRun(writer=events.append)

    # Act
    run.record_evaluation(_evaluation("satisfied", 0))
    run.record_evaluation(_evaluation("grader_error", 1))

    # Assert
    assert run.verdicts == ["satisfied", "grader_error"]
    assert events == []
