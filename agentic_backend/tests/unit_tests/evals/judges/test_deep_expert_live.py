"""Unit tests for `evals.judges.deep_expert_live`."""

from __future__ import annotations

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
