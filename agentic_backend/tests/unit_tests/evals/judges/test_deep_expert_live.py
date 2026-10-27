"""Unit tests for `evals.judges.deep_expert_live`."""

from __future__ import annotations

from typing import Any

import pytest

from evals.judges.deep_expert_live import judges

DEEP_ANSWER = "The deep answer."
BASELINE_ANSWER = "The expert answer."


def test_the_live_deep_judges_add_depth_to_the_live_experts_four() -> None:
    # Act
    names = [judge.name for judge in judges()]

    # Assert
    assert names == [
        "finished_or_outside",
        "urls_from_sources",
        "faithful_to_sources",
        "answers_the_question",
        "answer_without_preamble",
        "answer_without_closing_offer",
        "grader_satisfied",
        "deeper_than_expert",
    ]


def test_depth_skips_a_run_that_did_not_finish() -> None:
    """A failed run has no baseline; the depth view would raise instead of skipping."""
    # Arrange
    depth = judges()[-1]
    failed = {"finished": False, "side": "ours", "cause": "QuorumError"}

    # Act
    view = depth.view({"query": "q"}, failed, {})

    # Assert
    assert view is None


def test_depth_compares_the_deep_answer_with_the_baseline_on_a_finished_run() -> None:
    # Arrange
    depth = judges()[-1]
    output = {
        "finished": True,
        "answer": DEEP_ANSWER,
        "baseline_answer": BASELINE_ANSWER,
    }

    # Act
    view = depth.view({"query": "q"}, output, {})

    # Assert
    assert view == {
        "question": "q",
        "deep_answer": DEEP_ANSWER,
        "answer": BASELINE_ANSWER,
    }


def test_the_live_judges_skip_the_new_checks_when_the_run_failed() -> None:
    """A failed run has no answer to read; the checks must skip, and depth stays last."""
    # Arrange
    failed = {"finished": False, "side": "ours", "cause": "QuorumError"}
    new_checks = [
        judge
        for judge in judges()
        if judge.name in ("answer_without_preamble", "answer_without_closing_offer")
    ]

    # Act
    views = [judge.view({"query": "q"}, failed, {}) for judge in new_checks]

    # Assert
    assert (len(new_checks), views, judges()[-1].name) == (
        2,
        [None, None],
        "deeper_than_expert",
    )


def find_grader_judge() -> Any:
    return next(judge for judge in judges() if judge.name == "grader_satisfied")


@pytest.mark.parametrize(
    ("verdicts", "passes"),
    [
        (["satisfied"], True),
        (["needs_revision", "satisfied"], True),
        (["needs_revision", "max_iterations_reached"], False),
        (["max_iterations_reached"], False),
        (["satisfied", "needs_revision"], False),
        ([], False),
    ],
    ids=[
        "satisfied at once",
        "revised then satisfied",
        "revised then the round cap",
        "the round cap alone",
        "satisfied but not last",
        "the grader never ran",
    ],
)
def test_grader_satisfied_passes_only_when_the_last_verdict_is_satisfied(
    verdicts: list[str], passes: bool
) -> None:
    """A run that shipped on the round cap is a draft the grader never accepted; the eval must fail it."""
    # Arrange
    judge = find_grader_judge()
    output = {"finished": True, "grader_verdicts": verdicts}
    variables = judge.view({"query": "q"}, output, {})
    assert variables is not None
    assert judge.check is not None

    # Act
    result = judge.check(variables)

    # Assert
    assert result is passes


def test_grader_satisfied_skips_a_run_that_did_not_finish() -> None:
    """A failed run has no verdicts to judge; the outcome judge already reports it."""
    # Arrange
    failed = {"finished": False, "side": "ours", "cause": "QuorumError"}

    # Act
    view = find_grader_judge().view({"query": "q"}, failed, {})

    # Assert
    assert view is None
