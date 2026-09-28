"""Unit tests for `evals.helpers.ax`."""

from __future__ import annotations

import logging
import math
from types import SimpleNamespace
from typing import Any

import pytest

from evals.helpers import ax as ax_mod
from evals.helpers.judge import (
    JUDGE_ERROR,
    NOT_APPLICABLE,
    Judge,
    Verdict,
)


def _view(
    input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    return {}


class _Frame:
    """Records-shaped stand-in for the pandas frame `experiments.run` returns."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def to_dict(self, *, orient: str) -> list[dict[str, Any]]:
        assert orient == "records"
        return self.rows


def _ax_client(recorded: dict[str, Any], existing: list[Any]) -> Any:
    def _create_categorical(**kwargs: Any) -> Any:
        recorded.setdefault("configs", []).append(kwargs)
        return SimpleNamespace(name=kwargs["name"])

    def _annotate_examples(**kwargs: Any) -> Any:
        recorded.setdefault("annotations", []).append(kwargs)

    return SimpleNamespace(
        annotation_configs=SimpleNamespace(
            list=lambda **kwargs: SimpleNamespace(annotation_configs=list(existing)),
            create_categorical=_create_categorical,
        ),
        datasets=SimpleNamespace(annotate_examples=_annotate_examples),
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [(5, 5), ('{"a": 1}', {"a": 1}), ("not json", "not json")],
)
def test_decode_ax_value(value: Any, expected: Any) -> None:
    # Assert
    assert ax_mod.decode_ax_value(value) == expected


def test_annotate_sends_every_judge_label_per_row_without_score() -> None:
    # Arrange
    frame = _Frame(
        [
            {
                "example_id": "ex-1",
                "error": None,
                "eval.j1.label": "pass",
                "eval.j1.explanation": "routing matches",
                "eval.j2.label": "4",
                "eval.j2.explanation": "small gap",
            }
        ]
    )
    judges = [
        Judge("j1", "binary", _view, check=lambda variables: True),
        Judge("j2", "numeric", _view, prompt="{x}"),
    ]
    recorded: dict[str, Any] = {}

    # Act
    ax_mod.annotate(_ax_client(recorded, []), "space", "dataset-id", frame, judges)

    # Assert
    assert [kwargs["name"] for kwargs in recorded["configs"]] == ["j1", "j2"]
    assert [kwargs["space"] for kwargs in recorded["configs"]] == ["space", "space"]
    annotations = recorded["annotations"][0]["annotations"]
    assert annotations[0].record_id == "ex-1"
    values = annotations[0].values
    assert [(v.name, v.score, v.label, v.text) for v in values] == [
        ("j1", None, "pass", "routing matches"),
        ("j2", None, "4", "small gap"),
    ]


def test_annotate_reuses_existing_annotation_configs() -> None:
    # Arrange
    frame = _Frame(
        [
            {
                "example_id": "ex-1",
                "error": None,
                "eval.j1.label": "pass",
                "eval.j1.explanation": "ok",
                "eval.j2.label": "4",
                "eval.j2.explanation": "small gap",
            }
        ]
    )
    judges = [
        Judge("j1", "binary", _view, check=lambda variables: True),
        Judge("j2", "numeric", _view, prompt="{x}"),
    ]
    recorded: dict[str, Any] = {}

    # Act
    ax_mod.annotate(
        _ax_client(recorded, [SimpleNamespace(name="j1")]),
        "space",
        "dataset-id",
        frame,
        judges,
    )

    # Assert
    assert [kwargs["name"] for kwargs in recorded["configs"]] == ["j2"]


def test_annotate_skips_error_rows_and_unstorable_labels(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange
    frame = _Frame(
        [
            {
                "example_id": "ex-1",
                "error": "task blew up",
                "eval.j1.label": "pass",
                "eval.j1.explanation": "ignored",
            },
            {
                "example_id": "ex-2",
                "error": None,
                "eval.j1.label": NOT_APPLICABLE,
                "eval.j1.explanation": "",
            },
            {
                "example_id": "ex-3",
                "error": None,
                "eval.j1.label": JUDGE_ERROR,
                "eval.j1.explanation": "down",
            },
            {
                "example_id": "ex-4",
                "error": None,
                "eval.j1.label": None,
                "eval.j1.explanation": None,
            },
        ]
    )
    judges = [Judge("j1", "binary", _view, check=lambda variables: True)]
    recorded: dict[str, Any] = {}

    # Act
    with caplog.at_level(logging.WARNING, logger="agent"):
        ax_mod.annotate(_ax_client(recorded, []), "space", "dataset-id", frame, judges)

    # Assert
    assert recorded == {}
    assert "No judge labels to annotate" in caplog.text


def test_annotate_skips_rows_without_example_id() -> None:
    # Arrange
    frame = _Frame(
        [
            {
                "example_id": None,
                "error": None,
                "eval.j1.label": "pass",
                "eval.j1.explanation": "ok",
            }
        ]
    )
    judges = [Judge("j1", "binary", _view, check=lambda variables: True)]
    recorded: dict[str, Any] = {}

    # Act
    ax_mod.annotate(_ax_client(recorded, []), "space", "dataset-id", frame, judges)

    # Assert
    assert recorded == {}


def test_collect_returns_empty_verdicts_without_label_column() -> None:
    # Arrange
    frame = _Frame([{"example_id": "ex-1", "error": None}])
    judges = [Judge("j1", "binary", _view, check=lambda variables: True)]

    # Act
    results = ax_mod.collect(frame, judges)

    # Assert
    assert results.task_errors == []
    assert results.verdicts == {"j1": []}


def test_collect_reports_task_errors() -> None:
    # Arrange
    frame = _Frame(
        [
            {
                "example_id": "ex-1",
                "error": "task blew up",
                "eval.j1.label": None,
                "eval.j1.explanation": None,
            }
        ]
    )
    judges = [Judge("j1", "binary", _view, check=lambda variables: True)]

    # Act
    results = ax_mod.collect(frame, judges)

    # Assert
    assert results.task_errors == ["task blew up"]
    assert results.verdicts["j1"] == [
        Verdict(
            JUDGE_ERROR, explanation="The platform recorded no result for this judge."
        )
    ]


def test_collect_maps_valid_labels() -> None:
    # Arrange
    frame = _Frame(
        [
            {
                "example_id": "ex-1",
                "error": None,
                "eval.j1.label": "pass",
                "eval.j1.explanation": "ok",
            }
        ]
    )
    judges = [Judge("j1", "binary", _view, check=lambda variables: True)]

    # Act
    results = ax_mod.collect(frame, judges)

    # Assert
    assert results.task_errors == []
    assert results.verdicts["j1"] == [Verdict("pass", 1.0, "ok")]


def test_build_evaluator_decodes_json_strings_before_the_view() -> None:
    # Arrange
    seen: list[tuple[Any, Any]] = []

    def _recording_view(
        input: dict[str, Any], output: dict[str, Any], expected: dict[str, Any]
    ) -> dict[str, Any]:
        seen.append((input, expected))
        return {}

    judge = Judge("j", "binary", _recording_view, check=lambda variables: True)
    evaluator = ax_mod.build_evaluator(judge, None)

    # Act
    result = evaluator(input='{"q": 1}', output={"a": 2}, dataset_output='{"e": 3}')

    # Assert
    assert seen == [({"q": 1}, {"e": 3})]
    assert (result.score, result.label) == (1.0, "pass")


def test_build_evaluator_never_records_an_empty_explanation() -> None:
    # Arrange: code-check verdicts carry no explanation; AX Flight rejects an
    # all-null explanation column, so the evaluator must fill one in.
    judge = Judge("j", "binary", _view, check=lambda variables: True)
    evaluator = ax_mod.build_evaluator(judge, None)

    # Act
    result = evaluator(input='{"q": 1}', output={"a": 2}, dataset_output='{"e": 3}')

    # Assert
    assert result.explanation == "No explanation recorded."


def test_build_evaluator_never_records_a_null_score() -> None:
    # Arrange: AX Flight rejects an all-null score column, and a judge that
    # applies to one example and errors on it would otherwise send exactly that.
    judge = Judge("j", "numeric", _view, prompt="{x}")

    def _boom(prepared: Any) -> list[Any]:
        raise KeyError("bad request")

    classifier = SimpleNamespace(evaluate=_boom)
    evaluator = ax_mod.build_evaluator(judge, classifier)

    # Act
    result = evaluator(input='{"q": 1}', output={"a": 2}, dataset_output='{"e": 3}')

    # Assert
    assert result.label == "judge_error"
    assert result.score is not None
    assert math.isnan(result.score)
