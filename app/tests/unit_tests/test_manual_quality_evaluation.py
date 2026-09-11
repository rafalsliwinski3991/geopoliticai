"""Regression checks for the manual Phoenix evaluation runner's UI boundary."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

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


def test_route_correct_accepts_the_expected_branch() -> None:
    runner = _load_runner()
    output = {"destination": "other", "standalone_query": "q", "answer": "a"}
    reference = {"route_correct_destination": "other"}
    assert runner.route_correct(output=output, reference=reference) is True


def test_route_correct_rejects_a_misroute() -> None:
    runner = _load_runner()
    output = {"destination": "other", "standalone_query": "q", "answer": "a"}
    reference = {"route_correct_destination": "geopolitical"}
    assert runner.route_correct(output=output, reference=reference) is False


def test_judge_specs_cover_exactly_the_five_judges() -> None:
    runner = _load_runner()
    specs = runner.judge_specs()
    assert set(specs) == {
        "route_correct",
        "groundedness",
        "usefulness",
        "rewrite_quality",
        "report_fidelity",
    }
    assert specs["route_correct"].prompt is None
    assert specs["groundedness"].reference_key is None
    for name in ("usefulness", "rewrite_quality", "report_fidelity"):
        assert specs[name].prompt is not None
        assert specs[name].reference_key is not None


class _StubGraph:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self._results = list(results)
        self.calls: list[object] = []

    async def ainvoke(self, state: object, config: object = None) -> dict[str, Any]:
        self.calls.append(state)
        if not self._results:
            raise AssertionError("Stub graph ran out of scripted results")
        return self._results.pop(0)


def _patch_build_graph(
    monkeypatch: pytest.MonkeyPatch, results: list[dict[str, Any]]
) -> tuple[list[bool], _StubGraph]:
    graph_module = importlib.import_module("agents.orchestrator.graph")

    stub = _StubGraph(results)
    builds: list[bool] = []

    def fake_build(checkpointer: object = None) -> _StubGraph:
        builds.append(True)
        return stub

    monkeypatch.setattr(graph_module, "build_graph", fake_build)
    return builds, stub


def test_run_e2e_sends_initial_state_and_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds, stub = _patch_build_graph(
        monkeypatch,
        [
            {"destination": "geopolitical", "__interrupt__": ["pending"]},
            {"destination": "report", "__interrupt__": ["pending"]},
            {
                "messages": [
                    HumanMessage("Finland research citing [BBC](https://www.bbc.com/x)"),
                    AIMessage("SWEDEN REPORT SENTINEL"),
                ],
                "destination": "report",
                "standalone_query": "Why Sweden joined NATO",
            },
        ],
    )
    runner = _load_runner()
    outcome = asyncio.run(
        runner.run_e2e(
            {
                "turns": [
                    {"query": "  Why Finland?  ", "expect": "geopolitical"},
                    {"query": "What about Sweden?"},
                    {"resume": "approve"},
                ]
            }
        )
    )
    assert builds == [True]
    assert isinstance(stub.calls[0], dict)
    assert [
        message.content for message in stub.calls[0]["messages"]  # type: ignore[index]
    ] == ["Why Finland?"]
    assert [
        message.content for message in stub.calls[1]["messages"]  # type: ignore[index]
    ] == ["What about Sweden?"]
    assert isinstance(stub.calls[2], Command)
    assert outcome["answer"] == "SWEDEN REPORT SENTINEL"
    assert outcome["destination"] == "report"
    assert outcome["standalone_query"] == "Why Sweden joined NATO"
    assert "SWEDEN REPORT SENTINEL" not in outcome["conversation"]
    assert "bbc.com" in outcome["conversation"]


def test_run_e2e_resume_without_pending_interrupt_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_build_graph(monkeypatch, [])
    runner = _load_runner()
    with pytest.raises(RuntimeError, match="no pending interrupt"):
        asyncio.run(runner.run_e2e({"turns": [{"resume": "approve"}]}))


def test_run_e2e_rejects_a_turn_carrying_neither_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds, _ = _patch_build_graph(monkeypatch, [])
    runner = _load_runner()
    with pytest.raises(ValueError, match=r"each e2e turn needs"):
        asyncio.run(runner.run_e2e({"turns": [{"expect": "other"}]}))
    assert builds == []


def test_run_e2e_rejects_a_turn_carrying_both_resume_and_expect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds, _ = _patch_build_graph(monkeypatch, [])
    runner = _load_runner()
    with pytest.raises(ValueError, match=r"each e2e turn needs"):
        asyncio.run(runner.run_e2e({"turns": [{"resume": "approve", "expect": "report"}]}))
    assert builds == []


def test_run_e2e_rejects_an_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    builds, stub = _patch_build_graph(monkeypatch, [])
    runner = _load_runner()
    with pytest.raises(ValueError, match="must not be empty"):
        asyncio.run(runner.run_e2e({"turns": [{"query": "   "}]}))
    assert stub.calls == []


def test_run_e2e_setup_turn_misroute_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_build_graph(monkeypatch, [{"destination": "other"}])
    runner = _load_runner()
    with pytest.raises(RuntimeError, match=r"routed to 'other'"):
        asyncio.run(runner.run_e2e({"turns": [{"query": "q", "expect": "geopolitical"}]}))


def test_run_e2e_unknown_expect_rejects_before_any_graph_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds, stub = _patch_build_graph(monkeypatch, [])
    runner = _load_runner()
    with pytest.raises(ValueError, match="unknown expected destination"):
        asyncio.run(
            runner.run_e2e({"turns": [{"query": "q", "expect": "atlantis"}]})
        )
    assert builds == []
    assert stub.calls == []


def test_thread_output_excludes_the_final_ai_message_from_conversation() -> None:
    runner = _load_runner()
    result = {
        "messages": [
            HumanMessage("What did NATO decide at Vilnius?"),
            AIMessage("research: see [Reuters](https://www.reuters.com/vilnius)"),
            HumanMessage("Write the report"),
            AIMessage("REPORT_SENTINEL"),
        ],
        "destination": "report",
        "standalone_query": "Vilnius membership report",
    }
    outcome = runner.thread_output(result)
    assert outcome["answer"] == "REPORT_SENTINEL"
    assert outcome["destination"] == "report"
    assert outcome["standalone_query"] == "Vilnius membership report"
    assert "REPORT_SENTINEL" not in outcome["conversation"]
    assert "reuters.com" in outcome["conversation"]
