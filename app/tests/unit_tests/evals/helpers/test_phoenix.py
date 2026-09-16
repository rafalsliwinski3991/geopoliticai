"""Unit tests for `evals.helpers.phoenix`."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from evals.helpers import phoenix as phoenix_mod
from evals.helpers.judge import JUDGE_ERROR, Judge, Verdict


def _view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {"x": "y"}


def test_base_url_strips_traces_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(
        phoenix_mod, "get_trace_endpoint", lambda: "http://phoenix:6006/v1/traces/"
    )

    # Act
    url = phoenix_mod.base_url()

    # Assert
    assert url == "http://phoenix:6006"


def test_base_url_requires_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(phoenix_mod, "get_trace_endpoint", lambda: None)

    # Act + Assert
    with pytest.raises(ValueError, match="Missing collector endpoint"):
        phoenix_mod.base_url()


def test_base_url_rejects_wrong_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(
        phoenix_mod, "get_trace_endpoint", lambda: "http://phoenix:6006"
    )

    # Act + Assert
    with pytest.raises(RuntimeError, match="/v1/traces"):
        phoenix_mod.base_url()


def test_collect_maps_evaluation_runs() -> None:
    # Arrange
    judge = Judge("j", "binary", _view, check=lambda variables: True)
    eval_result = {
        "evaluation_runs": [
            SimpleNamespace(
                name="j", error=None, result={"label": "pass", "explanation": "ok"}
            ),
            SimpleNamespace(name="j", error="evaluator blew up", result=None),
            SimpleNamespace(
                name="unknown", error=None, result={"label": "pass", "explanation": ""}
            ),
        ]
    }
    task_result = {"task_runs": [{"error": "task blew up"}, {"error": None}]}

    # Act
    results = phoenix_mod.collect(task_result, eval_result, [judge])

    # Assert
    assert results.task_errors == ["task blew up"]
    assert results.verdicts["j"] == [
        Verdict("pass", 1.0, "ok"),
        Verdict(JUDGE_ERROR, explanation="evaluator blew up"),
    ]


@pytest.mark.anyio
async def test_build_evaluator_awaits_async_evaluate_only() -> None:
    # Arrange
    judge = Judge("j", "numeric", _view, prompt="{x}")
    outcome = SimpleNamespace(label="4", explanation="ok")

    def _sync_evaluate(prepared: Any) -> list[Any]:
        raise AssertionError("the sync evaluate must not be called")

    async def _async_evaluate(prepared: Any) -> list[Any]:
        return [outcome]

    classifier = SimpleNamespace(
        evaluate=_sync_evaluate, async_evaluate=_async_evaluate
    )
    evaluator = phoenix_mod.build_evaluator(judge, classifier)

    # Act
    result = await evaluator(input={"q": 1}, output={"a": 2}, reference={"r": 3})

    # Assert
    assert asyncio.iscoroutinefunction(evaluator)
    assert result == {"score": 0.75, "label": "4", "explanation": "ok"}
