"""Unit tests for `evals.helpers.judge`."""

from __future__ import annotations

import math
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from evals.helpers.judge import (
    JUDGE_ERROR,
    JUDGE_RETRIES,
    NOT_APPLICABLE,
    Judge,
    Verdict,
    async_score,
    markdown_link_urls,
    score,
    verdict_from_label,
)

View = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any] | None]


def _view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {"x": "y"}


def _never_called_view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    raise AssertionError("the view must not be called")


def test_judge_rejects_both_prompt_and_check() -> None:
    # Act + Assert
    with pytest.raises(ValueError, match="exactly one of prompt or check"):
        Judge("j", "binary", _view, prompt="{x}", check=lambda variables: True)


def test_judge_rejects_neither_prompt_nor_check() -> None:
    # Act + Assert
    with pytest.raises(ValueError, match="exactly one of prompt or check"):
        Judge("j", "binary", _view)


def test_judge_rejects_numeric_code_check() -> None:
    # Act + Assert
    with pytest.raises(ValueError, match="code checks must be binary"):
        Judge("j", "numeric", _view, check=lambda variables: True)


def test_judge_choices_by_kind() -> None:
    # Arrange
    binary = Judge("b", "binary", _view, check=lambda variables: True)
    numeric = Judge("n", "numeric", _view, prompt="{x}")

    # Assert
    assert binary.choices == {"fail": 0.0, "pass": 1.0}
    assert numeric.choices == {
        "1": 0.0,
        "2": 0.25,
        "3": 0.5,
        "4": 0.75,
        "5": 1.0,
    }


def test_score_returns_not_applicable_when_output_is_none() -> None:
    # Arrange
    judge = Judge("j", "binary", _never_called_view, check=lambda variables: True)

    # Act
    verdict = score(judge, None, {}, None, {})

    # Assert
    assert verdict == Verdict(
        NOT_APPLICABLE, explanation="The task produced no output."
    )


def test_score_returns_not_applicable_when_view_returns_none() -> None:
    # Arrange
    judge = Judge("j", "binary", lambda i, o, e: None, check=lambda variables: True)

    # Act
    verdict = score(judge, None, {}, {"answer": "x"}, {})

    # Assert
    assert verdict.label == NOT_APPLICABLE


@pytest.mark.parametrize(
    ("passed", "expected"),
    [(True, Verdict("pass", 1.0)), (False, Verdict("fail", 0.0))],
)
def test_score_runs_code_check(passed: bool, expected: Verdict) -> None:
    # Arrange
    judge = Judge("j", "binary", _view, check=lambda variables: passed)

    # Act
    verdict = score(judge, None, {}, {"answer": "x"}, {})

    # Assert
    assert verdict == expected


def test_score_records_judge_error_when_view_raises() -> None:
    # Arrange
    def _boom(
        input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
    ) -> dict[str, Any]:
        raise ValueError("boom")

    judge = Judge("j", "binary", _boom, check=lambda variables: True)

    # Act
    verdict = score(judge, None, {}, {"answer": "x"}, {})

    # Assert
    assert verdict.label == JUDGE_ERROR
    assert "ValueError" in verdict.explanation
    assert "boom" in verdict.explanation


def test_score_returns_verdict_for_valid_label() -> None:
    # Arrange
    judge = Judge("j", "numeric", _view, prompt="{x}")
    outcome = SimpleNamespace(label="4", explanation="ok")
    classifier = SimpleNamespace(evaluate=lambda prepared: [outcome])

    # Act
    verdict = score(judge, classifier, {}, {"answer": "x"}, {})

    # Assert
    assert verdict == Verdict("4", 0.75, "ok")


def test_score_retries_then_records_judge_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    judge = Judge("j", "numeric", _view, prompt="{x}")
    calls: list[Any] = []
    sleeps: list[float] = []

    def _boom(prepared: Any) -> list[Any]:
        calls.append(prepared)
        raise RuntimeError("judge down")

    def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("time.sleep", _sleep)
    classifier = SimpleNamespace(evaluate=_boom)

    # Act
    verdict = score(judge, classifier, {}, {"answer": "x"}, {})

    # Assert
    assert len(calls) == JUDGE_RETRIES
    assert sleeps == [1.0, 2.0, 4.0]
    assert verdict.label == JUDGE_ERROR
    assert f"after {JUDGE_RETRIES} attempts" in verdict.explanation


def test_score_accepts_valid_label_on_retry() -> None:
    # Arrange
    judge = Judge("j", "numeric", _view, prompt="{x}")
    outcomes = iter(
        [
            SimpleNamespace(label="9", explanation=""),
            SimpleNamespace(label="4", explanation="ok"),
        ]
    )
    classifier = SimpleNamespace(evaluate=lambda prepared: [next(outcomes)])

    # Act
    verdict = score(judge, classifier, {}, {"answer": "x"}, {})

    # Assert
    assert verdict == Verdict("4", 0.75, "ok")


@pytest.mark.anyio
async def test_async_score_returns_verdict_for_valid_label() -> None:
    # Arrange
    judge = Judge("j", "numeric", _view, prompt="{x}")
    outcome = SimpleNamespace(label="4", explanation="ok")

    async def _async_evaluate(prepared: Any) -> list[Any]:
        return [outcome]

    classifier = SimpleNamespace(async_evaluate=_async_evaluate)

    # Act
    verdict = await async_score(judge, classifier, {}, {"answer": "x"}, {})

    # Assert
    assert verdict == Verdict("4", 0.75, "ok")


@pytest.mark.anyio
async def test_async_score_retries_then_records_judge_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    judge = Judge("j", "numeric", _view, prompt="{x}")
    calls: list[Any] = []
    sleeps: list[float] = []

    async def _boom(prepared: Any) -> list[Any]:
        calls.append(prepared)
        raise RuntimeError("judge down")

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("asyncio.sleep", _sleep)
    classifier = SimpleNamespace(async_evaluate=_boom)

    # Act
    verdict = await async_score(judge, classifier, {}, {"answer": "x"}, {})

    # Assert
    assert len(calls) == JUDGE_RETRIES
    assert sleeps == [1.0, 2.0, 4.0]
    assert verdict.label == JUDGE_ERROR


@pytest.mark.anyio
async def test_async_score_accepts_valid_label_on_retry() -> None:
    # Arrange
    judge = Judge("j", "numeric", _view, prompt="{x}")
    outcomes = iter(
        [
            SimpleNamespace(label="9", explanation=""),
            SimpleNamespace(label="4", explanation="ok"),
        ]
    )

    async def _async_evaluate(prepared: Any) -> list[Any]:
        return [next(outcomes)]

    classifier = SimpleNamespace(async_evaluate=_async_evaluate)

    # Act
    verdict = await async_score(judge, classifier, {}, {"answer": "x"}, {})

    # Assert
    assert verdict == Verdict("4", 0.75, "ok")


@pytest.mark.anyio
async def test_async_score_runs_code_check_without_classifier() -> None:
    # Arrange
    judge = Judge("j", "binary", _view, check=lambda variables: True)

    # Act
    verdict = await async_score(judge, None, {}, {"answer": "x"}, {})

    # Assert
    assert verdict == Verdict("pass", 1.0)


def test_verdict_from_label_maps_known_labels() -> None:
    # Arrange
    judge = Judge("j", "binary", _view, check=lambda variables: True)

    # Assert
    assert verdict_from_label(judge, "pass", "ok") == Verdict("pass", 1.0, "ok")
    assert verdict_from_label(judge, NOT_APPLICABLE, "") == Verdict(
        NOT_APPLICABLE, explanation=""
    )


@pytest.mark.parametrize("label", [None, float("nan"), "judge_error", "unexpected"])
def test_verdict_from_label_maps_unknown_labels_to_judge_error(label: object) -> None:
    # Arrange
    judge = Judge("j", "binary", _view, check=lambda variables: True)

    # Act
    verdict = verdict_from_label(judge, label, "stored text")

    # Assert
    assert verdict.label == JUDGE_ERROR
    assert verdict.explanation == "stored text"


def test_verdict_from_label_uses_default_explanation_for_missing_text() -> None:
    # Arrange
    judge = Judge("j", "binary", _view, check=lambda variables: True)

    # Act
    verdict = verdict_from_label(judge, None, None)

    # Assert
    assert verdict.explanation == "The platform recorded no result for this judge."


def test_markdown_link_urls_extracts_link_targets() -> None:
    # Act
    urls = markdown_link_urls("[a](https://x.org/1) and [b](http://y.org)")

    # Assert
    assert urls == ["https://x.org/1", "http://y.org"]


def test_markdown_link_urls_ignores_bare_urls() -> None:
    # Assert
    assert markdown_link_urls("see https://z.org directly") == []


def test_numeric_not_a_choice_label() -> None:
    # Arrange
    judge = Judge("j", "numeric", _view, prompt="{x}")

    # Act
    verdict = verdict_from_label(judge, math.nan, "")

    # Assert
    assert verdict.label == JUDGE_ERROR
