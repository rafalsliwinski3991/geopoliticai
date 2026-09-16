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

RUNNER_PATH = Path(__file__).parents[3] / "evals" / "offline_evals.py"


def _load_runner() -> Any:
    spec = importlib.util.spec_from_file_location("offline_evals", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so dataclasses and other runtime machinery can
    # resolve the module by name.
    sys.modules["offline_evals"] = module
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


def test_annotate_ax_dataset_skips_rows_whose_task_run_errored() -> None:
    """A task error still gets judged against a `None` output; must not be annotated."""
    runner = _load_runner()
    ax_result = _AxResultFrame(
        [
            {
                "example_id": "ex-1",
                "error": "task blew up",
                "eval.orchestrator_quality.score": 1,
                "eval.orchestrator_quality.label": "1",
                "eval.orchestrator_quality.explanation": "scored a None output",
            },
            {
                "example_id": "ex-2",
                "error": None,
                "eval.orchestrator_quality.score": 4,
                "eval.orchestrator_quality.label": "4",
                "eval.orchestrator_quality.explanation": "small gap",
            },
        ]
    )
    recorded: dict[str, Any] = {}
    runner.annotate_ax_dataset(
        _annotation_client(recorded, []), "space", "dataset-id", ax_result
    )
    annotations = recorded["annotations"]["annotations"]
    assert [annotation.record_id for annotation in annotations] == ["ex-2"]


def test_annotate_ax_dataset_skips_judge_error_label() -> None:
    """`judge_error` isn't in SCORE_CHOICES; the categorical config would reject it."""
    runner = _load_runner()
    ax_result = _AxResultFrame(
        [
            {
                "example_id": "ex-1",
                "error": None,
                "eval.orchestrator_quality.score": None,
                "eval.orchestrator_quality.label": "judge_error",
                "eval.orchestrator_quality.explanation": "Judge failed after 3 attempts.",
            }
        ]
    )
    recorded: dict[str, Any] = {}
    with pytest.raises(RuntimeError, match="no judge scores"):
        runner.annotate_ax_dataset(
            _annotation_client(recorded, []), "space", "dataset-id", ax_result
        )


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


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('{"agent_name": "orchestrator"}', "must contain a list"),
        ('[{"agent_name": "orchestrator", "data": []}]', "non-empty list"),
        ('[{"agent_name": "orchestrator", "data": {}}]', "non-empty list"),
        ('[{"agent_name": "reporter", "data": [{}]}]', "no orchestrator entry"),
    ],
)
def test_load_examples_rejects_malformed_dataset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str, message: str
) -> None:
    runner = _load_runner()
    dataset = tmp_path / "dataset.json"
    dataset.write_text(content, encoding="utf-8")
    monkeypatch.setattr(runner, "DATASET_PATH", dataset)
    with pytest.raises(ValueError, match=message):
        runner.load_examples()


@pytest.mark.parametrize(
    ("value", "expected"),
    [(5, 5), ('{"a": 1}', {"a": 1}), ("not json", "not json")],
)
def test_decode_ax_value(value: Any, expected: Any) -> None:
    runner = _load_runner()
    assert runner.decode_ax_value(value) == expected


def test_phoenix_base_url_strips_traces_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(
        runner, "get_trace_endpoint", lambda: "http://phoenix:6006/v1/traces/"
    )
    assert runner.phoenix_base_url() == "http://phoenix:6006"


def test_phoenix_base_url_requires_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _load_runner()
    monkeypatch.setattr(runner, "get_trace_endpoint", lambda: None)
    with pytest.raises(ValueError, match="Missing collector endpoint"):
        runner.phoenix_base_url()


def test_phoenix_base_url_rejects_wrong_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner()
    monkeypatch.setattr(runner, "get_trace_endpoint", lambda: "http://phoenix:6006")
    with pytest.raises(RuntimeError, match="/v1/traces"):
        runner.phoenix_base_url()


def test_ax_judge_returns_judge_score() -> None:
    runner = _load_runner()
    score = SimpleNamespace(score=4, label="4", explanation="small gap")
    judge = SimpleNamespace(evaluate=lambda eval_input: [score])
    result = runner.build_ax_judge(judge)(
        input='{"q": 1}', output={"a": 2}, dataset_output={"a": 2}
    )
    assert (result.score, result.label, result.explanation) == (4, "4", "small gap")


def test_ax_judge_records_failure_after_retries() -> None:
    runner = _load_runner()
    calls: list[dict[str, Any]] = []

    def _boom(eval_input: dict[str, Any]) -> list[Any]:
        calls.append(eval_input)
        raise RuntimeError("judge down")

    result = runner.build_ax_judge(SimpleNamespace(evaluate=_boom))(
        input='{"q": 1}', output={"a": 2}, dataset_output={"a": 2}
    )
    assert len(calls) == runner.JUDGE_RETRIES
    assert calls[0]["input"] == {"q": 1}
    # score=None (not 0) so `.dropna()` excludes it from the average, matching
    # the Phoenix path's exclusion of errored evaluator runs.
    assert (result.score, result.label) == (None, "judge_error")


@pytest.mark.anyio
async def test_phoenix_judge_returns_judge_score() -> None:
    runner = _load_runner()
    score = SimpleNamespace(score=4, label="4", explanation="small gap")

    async def _async_evaluate(eval_input: dict[str, Any]) -> list[Any]:
        return [score]

    judge = SimpleNamespace(async_evaluate=_async_evaluate)
    result = await runner.build_phoenix_judge(judge)(
        input={"q": 1}, output={"a": 2}, reference={"a": 2}
    )
    assert result == {"score": 4, "label": "4", "explanation": "small gap"}


@pytest.mark.anyio
async def test_phoenix_judge_retries_then_records_failure() -> None:
    """Phoenix never retries a judge failure itself (see build_phoenix_judge's
    docstring), so this file must do it, the same way build_ax_judge does."""
    runner = _load_runner()
    calls: list[dict[str, Any]] = []

    async def _boom(eval_input: dict[str, Any]) -> list[Any]:
        calls.append(eval_input)
        raise RuntimeError("judge down")

    judge = SimpleNamespace(async_evaluate=_boom)
    result = await runner.build_phoenix_judge(judge)(
        input={"q": 1}, output={"a": 2}, reference={"a": 2}
    )
    assert len(calls) == runner.JUDGE_RETRIES
    assert calls[0]["input"] == {"q": 1}
    assert result == {
        "score": None,
        "label": "judge_error",
        "explanation": f"Judge failed after {runner.JUDGE_RETRIES} attempts.",
    }


def test_judge_view_extracts_final_answer_and_drops_message_envelope() -> None:
    runner = _load_runner()
    payload = {
        "messages": [
            {"type": "human", "data": {"type": "human", "content": "hi"}},
            {"type": "ai", "data": {"type": "ai", "content": "first"}},
            {"type": "ai", "data": {"type": "ai", "content": "final answer"}},
        ],
        "destination": "geopolitical",
        "standalone_query": "hi?",
    }
    assert runner.judge_view(payload) == {
        "destination": "geopolitical",
        "standalone_query": "hi?",
        "final_answer": "final answer",
    }


def test_judge_view_handles_no_ai_message() -> None:
    runner = _load_runner()
    payload = {"messages": [], "destination": "other", "standalone_query": "hi"}
    assert runner.judge_view(payload)["final_answer"] == ""
