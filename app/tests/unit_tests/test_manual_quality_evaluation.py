"""Regression checks for the manual Phoenix evaluation runner's UI boundary."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

RUNNER_PATH = Path(__file__).parents[1] / "manual_quality" / "basic_agent_evaluation.py"
PROMPTS_PATH = Path(__file__).parents[1] / "manual_quality" / "judge_prompts.py"


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so dataclasses and other runtime machinery can
    # resolve the module by name.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_runner() -> Any:
    # The runner imports `judge_prompts` from its own directory, which pytest
    # does not put on `sys.path`; the loader must, or the exec_module below
    # raises ModuleNotFoundError.
    parent = str(RUNNER_PATH.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return _load_module("basic_agent_evaluation", RUNNER_PATH)


def _load_prompts() -> Any:
    return _load_module("judge_prompts", PROMPTS_PATH)


def test_rubric_prompts_live_in_judge_prompts_module() -> None:
    """The four prompts are moved, not duplicated, and the runner imports them."""
    prompts = _load_prompts()
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    module_assignments = [
        node.targets[0].id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
    ]
    for name in (
        "GROUNDEDNESS_PROMPT",
        "USEFULNESS_PROMPT",
        "REWRITE_QUALITY_PROMPT",
        "REPORT_FIDELITY_PROMPT",
    ):
        assert getattr(_load_runner(), name) == getattr(prompts, name)
        assert name not in module_assignments


def _write_cases(tmp_path: Path, content: str) -> Any:
    runner = _load_runner()
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(content, encoding="utf-8")
    runner.CASES_PATH = cases_path
    return runner


def test_live_results_use_phoenix_native_output() -> None:
    """Keep result presentation in Phoenix instead of custom terminal rendering."""
    # Arrange
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    printed_expressions = [
        ast.unparse(node.args[0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
        and node.args
    ]
    printed_output = "\n".join(printed_expressions)
    evaluate_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "evaluate_experiment"
    ]

    # Assert
    assert "validate_and_print_evaluations" not in function_names
    assert "expert experiment:" not in printed_output
    assert "orchestrator experiment:" not in printed_output
    assert "score=" not in printed_output
    assert "explanation:" not in printed_output
    assert "Advisory reviewer evidence" not in printed_output
    assert len(evaluate_calls) == 1
    assert any(
        keyword.arg == "print_summary"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in evaluate_calls[0].keywords
    )


def test_load_cases_rejects_a_json_object(tmp_path: Path) -> None:
    runner = _write_cases(
        tmp_path,
        json.dumps({"expert": {"id": "x", "input": {}, "output": {}, "metadata": {}}}),
    )
    with pytest.raises(ValueError, match="non-empty list of cases"):
        runner.load_cases()


def test_load_cases_rejects_an_empty_list(tmp_path: Path) -> None:
    runner = _write_cases(tmp_path, json.dumps([]))
    with pytest.raises(ValueError, match="non-empty list of cases"):
        runner.load_cases()


def test_load_cases_rejects_a_missing_field(tmp_path: Path) -> None:
    case = {
        "agent": "expert",
        "id": "expert-x",
        "input": {"query": "q"},
        "metadata": {},
    }
    runner = _write_cases(tmp_path, json.dumps([case]))
    with pytest.raises(ValueError, match=r"each case needs exactly"):
        runner.load_cases()


def test_load_cases_rejects_an_extra_field(tmp_path: Path) -> None:
    case = {
        "agent": "expert",
        "id": "expert-x",
        "input": {"query": "q"},
        "output": {},
        "metadata": {},
        "extra": 1,
    }
    runner = _write_cases(tmp_path, json.dumps([case]))
    with pytest.raises(ValueError, match=r"each case needs exactly"):
        runner.load_cases()


def test_load_cases_rejects_an_unknown_agent(tmp_path: Path) -> None:
    case = {
        "agent": "unknown",
        "id": "x",
        "input": {},
        "output": {},
        "metadata": {},
    }
    runner = _write_cases(tmp_path, json.dumps([case]))
    with pytest.raises(ValueError, match="unknown agent"):
        runner.load_cases()


def test_load_cases_rejects_a_blank_id(tmp_path: Path) -> None:
    case = {
        "agent": "expert",
        "id": "   ",
        "input": {},
        "output": {},
        "metadata": {},
    }
    runner = _write_cases(tmp_path, json.dumps([case]))
    with pytest.raises(ValueError, match=r"case\.id must be a non-empty string"):
        runner.load_cases()


def test_load_cases_rejects_a_duplicate_id(tmp_path: Path) -> None:
    case = {
        "agent": "expert",
        "id": "expert-x",
        "input": {},
        "output": {},
        "metadata": {},
    }
    runner = _write_cases(tmp_path, json.dumps([case, dict(case)]))
    with pytest.raises(ValueError, match="duplicate case id"):
        runner.load_cases()


def test_load_cases_rejects_a_non_object_case(tmp_path: Path) -> None:
    runner = _write_cases(tmp_path, json.dumps(["not-an-object"]))
    with pytest.raises(ValueError, match=r"each case needs exactly"):
        runner.load_cases()


def test_load_cases_rejects_a_non_object_field(tmp_path: Path) -> None:
    case = {
        "agent": "expert",
        "id": "x",
        "input": "not-an-object",
        "output": {},
        "metadata": {},
    }
    runner = _write_cases(tmp_path, json.dumps([case]))
    with pytest.raises(ValueError, match=r"must be an object"):
        runner.load_cases()


def test_load_cases_accepts_the_real_shipped_cases_json() -> None:
    runner = _load_runner()
    cases = runner.load_cases()
    assert isinstance(cases, list)
    assert {case["id"] for case in cases} == {
        "expert-finland-nato-v1",
        "expert-niger-coup-v1",
        "expert-taiwan-strait-v1",
        "orchestrator-sweden-follow-up-v1",
        "orchestrator-eu-sanctions-follow-up-v1",
        "reporter-vilnius-summit-v1",
    }
    assert {case["agent"] for case in cases} == {
        "expert",
        "orchestrator",
        "reporter",
    }


def test_route_correct_accepts_a_case_expecting_other() -> None:
    runner = _load_runner()
    output = {"destination": "other", "standalone_query": "q", "answer": "a"}
    reference = {"destination": "other"}
    assert runner.route_correct(output=output, reference=reference) is True
