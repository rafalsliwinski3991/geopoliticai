"""Unit tests for `evals.helpers.run`."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest

from evals.helpers import phoenix as phoenix_mod
from evals.helpers import run as run_mod
from evals.helpers.judge import JUDGE_ERROR, NOT_APPLICABLE, Judge, Results, Verdict


async def _task(input: dict[str, Any]) -> dict[str, Any]:
    return {"done": True}


def test_load_examples_returns_pairs_without_names(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "x.json"
    path.write_text(
        json.dumps([{"name": "a", "input": {"q": 1}, "output": {"a": 2}}]),
        encoding="utf-8",
    )

    # Act
    examples = run_mod.load_examples(path)

    # Assert
    assert examples == [{"input": {"q": 1}, "output": {"a": 2}}]


def test_load_examples_reads_the_documented_wrapper(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "x.json"
    path.write_text(
        json.dumps(
            {
                "description": "what this dataset is for",
                "cases": [
                    {
                        "name": "a",
                        "description": "what this case is about",
                        "input": {"q": 1},
                        "output": {"a": 2},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    # Act
    examples = run_mod.load_examples(path)

    # Assert
    assert examples == [{"input": {"q": 1}, "output": {"a": 2}}]


@pytest.mark.parametrize(
    "wrapper",
    [
        {"description": "", "cases": [{"name": "a", "input": {}, "output": {}}]},
        {"cases": [{"name": "a", "input": {}, "output": {}}]},
    ],
)
def test_load_examples_rejects_a_wrapper_without_a_description(
    tmp_path: Path, wrapper: dict[str, Any]
) -> None:
    # Arrange
    path = tmp_path / "x.json"
    path.write_text(json.dumps(wrapper), encoding="utf-8")

    # Act + Assert
    with pytest.raises(ValueError, match="wrapper dataset needs a description"):
        run_mod.load_examples(path)


def test_load_examples_rejects_a_non_string_case_description(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "x.json"
    path.write_text(
        json.dumps([{"name": "a", "description": 5, "input": {}, "output": {}}]),
        encoding="utf-8",
    )

    # Act + Assert
    with pytest.raises(ValueError, match="description must be a string"):
        run_mod.load_examples(path)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ('{"name": "a"}', "wrapper dataset needs a description"),
        ('{"description": "doc", "cases": null}', "non-empty list"),
        ("[]", "non-empty list"),
        ('[{"input": {}, "output": {}}]', "needs a string name"),
        ('[{"name": "a", "output": {}}]', "needs a string name"),
        ('[{"name": "a", "input": [], "output": {}}]', "needs a string name"),
        ('[{"name": "a", "input": {}}]', "needs a string name"),
    ],
)
def test_load_examples_rejects_malformed_files(
    tmp_path: Path, content: str, message: str
) -> None:
    # Arrange
    path = tmp_path / "x.json"
    path.write_text(content, encoding="utf-8")

    # Act + Assert
    with pytest.raises(ValueError, match=message):
        run_mod.load_examples(path)


def test_load_examples_rejects_duplicate_names(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "x.json"
    example = {"name": "a", "input": {}, "output": {}}
    path.write_text(json.dumps([example, example]), encoding="utf-8")

    # Act + Assert
    with pytest.raises(ValueError, match="duplicate example name"):
        run_mod.load_examples(path)


def test_dataset_name_hashes_file_content(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "x.json"
    path.write_text("one", encoding="utf-8")
    first = run_mod.dataset_name("test-eval", path)

    # Act
    path.write_text("one!", encoding="utf-8")
    second = run_mod.dataset_name("test-eval", path)

    # Assert
    assert first.startswith("geopoliticai-test-eval-")
    assert first != second


def test_dataset_name_is_stable_for_unchanged_content(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "x.json"
    path.write_text("same", encoding="utf-8")

    # Act
    first = run_mod.dataset_name("test-eval", path)
    second = run_mod.dataset_name("test-eval", path)

    # Assert
    assert first == second


def test_experiment_name_matches_commit_and_time() -> None:
    # Act
    name = run_mod.experiment_name("test-eval")

    # Assert
    assert re.fullmatch(r"test-eval-[0-9a-f]+-\d{8}T\d{6}Z", name)


def test_experiment_name_falls_back_without_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    def _fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError("no git")

    monkeypatch.setattr(subprocess, "run", _fail)

    # Act
    name = run_mod.experiment_name("test-eval")

    # Assert
    assert re.fullmatch(r"test-eval-nogit-\d{8}T\d{6}Z", name)


def test_failures_allows_numeric_average_at_minimum() -> None:
    # Arrange
    judge = Judge("q", "numeric", lambda i, o, e: {}, prompt="{x}")
    results = Results(
        task_errors=[], verdicts={"q": [Verdict("4", 0.75), Verdict("4", 0.75)]}
    )

    # Act
    problems = run_mod.failures(results, [judge], example_count=2)

    # Assert
    assert problems == []


def test_failures_reports_numeric_average_below_minimum() -> None:
    # Arrange
    judge = Judge("q", "numeric", lambda i, o, e: {}, prompt="{x}")
    results = Results(task_errors=[], verdicts={"q": [Verdict("3", 0.5)]})

    # Act
    problems = run_mod.failures(results, [judge], example_count=1)

    # Assert
    assert problems == ["q: average 0.50 is below 0.75"]


def test_failures_allows_binary_average_at_one() -> None:
    # Arrange
    judge = Judge("b", "binary", lambda i, o, e: {}, prompt="{x}")
    results = Results(
        task_errors=[], verdicts={"b": [Verdict("pass", 1.0), Verdict("pass", 1.0)]}
    )

    # Act
    problems = run_mod.failures(results, [judge], example_count=2)

    # Assert
    assert problems == []


def test_failures_reports_binary_average_below_one() -> None:
    # Arrange
    judge = Judge("b", "binary", lambda i, o, e: {}, prompt="{x}")
    results = Results(
        task_errors=[], verdicts={"b": [Verdict("pass", 1.0), Verdict("fail", 0.0)]}
    )

    # Act
    problems = run_mod.failures(results, [judge], example_count=2)

    # Assert
    assert problems == ["b: average 0.50 is below 1.00"]


def test_failures_reports_any_judge_error() -> None:
    # Arrange
    judge = Judge("b", "binary", lambda i, o, e: {}, prompt="{x}")
    results = Results(
        task_errors=[],
        verdicts={
            "b": [Verdict("pass", 1.0), Verdict(JUDGE_ERROR, explanation="down")]
        },
    )

    # Act
    problems = run_mod.failures(results, [judge], example_count=2)

    # Assert
    assert problems == ["b: 1 judge error(s); first: down"]


def test_failures_allows_all_not_applicable() -> None:
    # Arrange
    judge = Judge("b", "binary", lambda i, o, e: {}, prompt="{x}")
    results = Results(
        task_errors=[],
        verdicts={"b": [Verdict(NOT_APPLICABLE), Verdict(NOT_APPLICABLE)]},
    )

    # Act
    problems = run_mod.failures(results, [judge], example_count=2)

    # Assert
    assert problems == []


def test_failures_reports_missing_verdicts() -> None:
    # Arrange
    judge = Judge("b", "binary", lambda i, o, e: {}, prompt="{x}")
    results = Results(task_errors=[], verdicts={"b": [Verdict("pass", 1.0)]})

    # Act
    problems = run_mod.failures(results, [judge], example_count=2)

    # Assert
    assert problems == ["b: 1 results for 2 examples"]


def test_failures_reports_task_errors() -> None:
    # Arrange
    results = Results(task_errors=["task blew up"], verdicts={})

    # Act
    problems = run_mod.failures(results, [], example_count=1)

    # Assert
    assert problems == ["task failed: task blew up"]


@pytest.mark.anyio
async def test_run_passes_and_needs_no_brave_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.delenv("BRAVE_SEARCH_KEY", raising=False)
    monkeypatch.delenv("ARIZE_PLATFORM", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(run_mod, "init_environment", lambda *a, **kw: None)
    monkeypatch.setattr(run_mod, "init_tracing", lambda: True)
    monkeypatch.setattr(run_mod, "build_classifiers", lambda judges: {})
    received: dict[str, Any] = {}

    async def _fake_run(**kwargs: Any) -> Results:
        received.update(kwargs)
        return Results(task_errors=[], verdicts={"b": [Verdict("pass", 1.0)]})

    monkeypatch.setattr(phoenix_mod, "run", _fake_run)
    path = tmp_path / "d.json"
    path.write_text(
        json.dumps([{"name": "a", "input": {}, "output": {}}]), encoding="utf-8"
    )
    judge = Judge("b", "binary", lambda i, o, e: {}, check=lambda variables: True)

    # Act
    await run_mod.run(
        eval_name="test-eval",
        dataset_path=path,
        task=_task,
        judges=[judge],
    )

    # Assert
    assert received["dataset_name"] == run_mod.dataset_name("test-eval", path)
    assert received["judges"] == [judge]


@pytest.mark.anyio
async def test_run_exits_nonzero_on_failing_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    monkeypatch.delenv("BRAVE_SEARCH_KEY", raising=False)
    monkeypatch.delenv("ARIZE_PLATFORM", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(run_mod, "init_environment", lambda *a, **kw: None)
    monkeypatch.setattr(run_mod, "init_tracing", lambda: True)
    monkeypatch.setattr(run_mod, "build_classifiers", lambda judges: {})

    async def _fake_run(**kwargs: Any) -> Results:
        return Results(task_errors=[], verdicts={"b": [Verdict("fail", 0.0)]})

    monkeypatch.setattr(phoenix_mod, "run", _fake_run)
    path = tmp_path / "d.json"
    path.write_text(
        json.dumps([{"name": "a", "input": {}, "output": {}}]), encoding="utf-8"
    )
    judge = Judge("b", "binary", lambda i, o, e: {}, check=lambda variables: False)

    # Act + Assert
    with pytest.raises(SystemExit) as exc:
        await run_mod.run(
            eval_name="test-eval", dataset_path=path, task=_task, judges=[judge]
        )
    assert exc.value.code == 1


def test_task_alias_is_a_coroutine_factory() -> None:
    # Assert
    coroutine = _task({})
    assert isinstance(coroutine, Coroutine)
    coroutine.close()
