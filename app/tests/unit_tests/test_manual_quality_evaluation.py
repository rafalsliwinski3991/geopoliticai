"""Offline checks for the manual orchestrator evaluation runner.

The runner talks to live services only inside `main`; these tests load the
module and exercise its pure helpers with fakes so a regression fails here
before any paid run is attempted.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import BaseMessage, messages_from_dict

RUNNER_PATH = Path(__file__).parents[1] / "manual_quality" / "basic_agent_evaluation.py"


def _load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("basic_agent_evaluation", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so dataclasses and other runtime machinery can
    # resolve the module by name.
    sys.modules["basic_agent_evaluation"] = module
    spec.loader.exec_module(module)
    return module


def test_load_examples_returns_validated_orchestrator_cases() -> None:
    runner = _load_runner()
    examples = runner.load_examples()
    assert examples
    for example in examples:
        messages = messages_from_dict(example["input"]["messages"])
        assert messages
        assert all(isinstance(message, BaseMessage) for message in messages)
        assert example["output"]["destination"] in {
            "geopolitical",
            "other",
            "report",
        }


class _AxResultFrame:
    """Records-shaped stand-in for the pandas frame `experiments.run` returns."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def to_dict(self, *, orient: str) -> list[dict[str, Any]]:
        assert orient == "records"
        return self.rows


def _annotation_client(recorded: dict[str, Any], configs: list[Any]) -> Any:
    return SimpleNamespace(
        annotation_configs=SimpleNamespace(
            list=lambda **kwargs: SimpleNamespace(annotation_configs=configs),
            create_categorical=lambda **kwargs: recorded.setdefault("config", kwargs),
        ),
        datasets=SimpleNamespace(
            annotate_examples=lambda **kwargs: recorded.setdefault(
                "annotations", kwargs
            ),
        ),
    )


def test_annotate_ax_dataset_sends_label_and_reasoning_without_score() -> None:
    runner = _load_runner()
    ax_result = _AxResultFrame(
        [
            {
                "example_id": "ex-1",
                "error": None,
                "eval.orchestrator_quality.score": 5,
                "eval.orchestrator_quality.label": "5",
                "eval.orchestrator_quality.explanation": "routing matches",
            },
            {
                "example_id": "ex-2",
                "error": None,
                "eval.orchestrator_quality.score": 2,
                "eval.orchestrator_quality.label": "2",
                "eval.orchestrator_quality.explanation": "wrong destination",
            },
        ]
    )
    recorded: dict[str, Any] = {}
    runner.annotate_ax_dataset(
        _annotation_client(recorded, []), "space", "dataset-id", ax_result
    )

    assert recorded["config"]["name"] == "orchestrator_quality"
    annotations = recorded["annotations"]["annotations"]
    assert [annotation.record_id for annotation in annotations] == ["ex-1", "ex-2"]
    for annotation, expected in zip(
        annotations,
        [("5", "routing matches"), ("2", "wrong destination")],
        strict=True,
    ):
        value = annotation.values[0]
        assert value.name == "orchestrator_quality"
        # AX derives a categorical score from the label; sending one is a 422.
        assert value.score is None
        assert value.label == expected[0]
        assert value.text == expected[1]


def test_annotate_ax_dataset_skips_rows_without_judge_scores() -> None:
    runner = _load_runner()
    ax_result = _AxResultFrame(
        [
            {
                "example_id": "ex-1",
                "error": "task blew up",
                "eval.orchestrator_quality.score": None,
                "eval.orchestrator_quality.label": None,
                "eval.orchestrator_quality.explanation": None,
            }
        ]
    )
    recorded: dict[str, Any] = {}
    with pytest.raises(RuntimeError, match="no judge scores"):
        runner.annotate_ax_dataset(
            _annotation_client(recorded, []), "space", "dataset-id", ax_result
        )
    assert "annotations" not in recorded


def test_annotate_ax_dataset_reuses_existing_annotation_config() -> None:
    runner = _load_runner()
    ax_result = _AxResultFrame(
        [
            {
                "example_id": "ex-1",
                "eval.orchestrator_quality.score": 4,
                "eval.orchestrator_quality.label": "4",
                "eval.orchestrator_quality.explanation": "small gap",
            }
        ]
    )
    recorded: dict[str, Any] = {}
    existing_config = SimpleNamespace(name="orchestrator_quality")
    runner.annotate_ax_dataset(
        _annotation_client(recorded, [existing_config]),
        "space",
        "dataset-id",
        ax_result,
    )

    assert "config" not in recorded
    annotations = recorded["annotations"]["annotations"]
    assert annotations[0].values[0].label == "4"


def test_min_avg_score_gate_passes_at_threshold() -> None:
    runner = _load_runner()
    runner.ensure_min_avg_score(runner.MIN_AVG_SCORE)


def test_min_avg_score_gate_fails_below_threshold() -> None:
    runner = _load_runner()
    with pytest.raises(SystemExit):
        runner.ensure_min_avg_score(runner.MIN_AVG_SCORE - 0.1)


def test_min_avg_score_gate_fails_without_scores() -> None:
    runner = _load_runner()
    with pytest.raises(SystemExit):
        runner.ensure_min_avg_score(None)
