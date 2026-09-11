"""Regression checks for the manual Phoenix evaluation runner's UI boundary."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
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
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
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


NESTED_FIXTURE = {
    "expert": [
        {
            "id": "e1",
            "input": {"query": "q"},
            "output": {"usefulness_required_points": ["point"]},
            "metadata": {},
        }
    ],
    "orchestrator": [
        {
            "id": "o1",
            "input": {"messages": []},
            "output": {
                "route_correct_destination": "other",
                "rewrite_quality_intent": "intent",
            },
            "metadata": {},
        }
    ],
    "report": [
        {
            "id": "r1",
            "input": {"messages": [], "resume_actions": []},
            "output": {"report_fidelity_outline": "outline"},
            "metadata": {},
        }
    ],
    "e2e": [
        {
            "id": "z1",
            "input": {"turns": [{"query": "q"}]},
            "output": {
                "route_correct_destination": "geopolitical",
                "rewrite_quality_intent": "intent",
                "usefulness_required_points": ["point"],
            },
            "metadata": {},
        }
    ],
}


def _nested(**overrides: Any) -> str:
    """Dump a nested fixture with whole-kind or whole-case overrides."""
    fixture = json.loads(json.dumps(NESTED_FIXTURE))
    for kind, value in overrides.items():
        fixture[kind] = value
    return json.dumps(fixture)


def _case(**field_overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = json.loads(json.dumps(NESTED_FIXTURE["report"][0]))
    case.update(field_overrides)
    return case


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


def test_load_cases_rejects_a_json_list(tmp_path: Path) -> None:
    runner = _write_cases(
        tmp_path,
        json.dumps([{"id": "x", "input": {}, "output": {}, "metadata": {}}]),
    )
    with pytest.raises(ValueError, match="non-empty object keyed by kind"):
        runner.load_cases()


def test_load_cases_rejects_an_empty_object(tmp_path: Path) -> None:
    runner = _write_cases(tmp_path, json.dumps({}))
    with pytest.raises(ValueError, match="non-empty object keyed by kind"):
        runner.load_cases()


def test_load_cases_rejects_an_unknown_kind(tmp_path: Path) -> None:
    runner = _write_cases(tmp_path, _nested(unknown=[_case()]))
    with pytest.raises(ValueError, match="must hold exactly the kinds"):
        runner.load_cases()


def test_load_cases_rejects_a_missing_kind(tmp_path: Path) -> None:
    fixture = json.loads(json.dumps(NESTED_FIXTURE))
    del fixture["e2e"]
    runner = _write_cases(tmp_path, json.dumps(fixture))
    with pytest.raises(ValueError, match="must hold exactly the kinds"):
        runner.load_cases()


def test_load_cases_rejects_an_empty_kind(tmp_path: Path) -> None:
    runner = _write_cases(tmp_path, _nested(report=[]))
    with pytest.raises(ValueError, match="non-empty list of cases"):
        runner.load_cases()


def test_load_cases_rejects_a_missing_field(tmp_path: Path) -> None:
    case = _case()
    del case["output"]
    runner = _write_cases(tmp_path, _nested(report=[case]))
    with pytest.raises(ValueError, match=r"each case needs exactly"):
        runner.load_cases()


def test_load_cases_rejects_an_extra_field(tmp_path: Path) -> None:
    runner = _write_cases(tmp_path, _nested(report=[_case(extra=1)]))
    with pytest.raises(ValueError, match=r"each case needs exactly"):
        runner.load_cases()


def test_load_cases_rejects_a_blank_id(tmp_path: Path) -> None:
    runner = _write_cases(tmp_path, _nested(report=[_case(id="   ")]))
    with pytest.raises(ValueError, match=r"case\.id must be a non-empty string"):
        runner.load_cases()


def test_load_cases_rejects_a_duplicate_id_within_a_kind(tmp_path: Path) -> None:
    runner = _write_cases(tmp_path, _nested(report=[_case(), _case()]))
    with pytest.raises(ValueError, match="duplicate case id"):
        runner.load_cases()


def test_load_cases_rejects_a_duplicate_id_across_kinds(tmp_path: Path) -> None:
    expert = json.loads(json.dumps(NESTED_FIXTURE["expert"][0]))
    expert["id"] = "shared"
    e2e = json.loads(json.dumps(NESTED_FIXTURE["e2e"][0]))
    e2e["id"] = "shared"
    runner = _write_cases(tmp_path, _nested(expert=[expert], e2e=[e2e]))
    with pytest.raises(ValueError, match="duplicate case id: shared"):
        runner.load_cases()


def test_load_cases_rejects_a_non_object_case(tmp_path: Path) -> None:
    runner = _write_cases(tmp_path, _nested(report=["not-an-object"]))
    with pytest.raises(ValueError, match=r"each case needs exactly"):
        runner.load_cases()


def test_load_cases_rejects_a_non_object_field(tmp_path: Path) -> None:
    runner = _write_cases(tmp_path, _nested(report=[_case(input="not-an-object")]))
    with pytest.raises(ValueError, match=r"must be an object"):
        runner.load_cases()


def test_load_cases_rejects_a_missing_reference_key_for_report(
    tmp_path: Path,
) -> None:
    case = _case()
    del case["output"]["report_fidelity_outline"]
    runner = _write_cases(tmp_path, _nested(report=[case]))
    with pytest.raises(ValueError, match=r"r1 is missing .+report_fidelity_outline"):
        runner.load_cases()


def test_load_cases_rejects_a_missing_reference_key_for_e2e(
    tmp_path: Path,
) -> None:
    case = json.loads(json.dumps(NESTED_FIXTURE["e2e"][0]))
    del case["output"]["rewrite_quality_intent"]
    runner = _write_cases(tmp_path, _nested(e2e=[case]))
    with pytest.raises(ValueError, match=r"z1 is missing .+rewrite_quality_intent"):
        runner.load_cases()


def test_load_cases_accepts_the_real_shipped_cases_json() -> None:
    runner = _load_runner()
    cases = runner.load_cases()
    assert isinstance(cases, dict)
    assert set(cases) == {"expert", "orchestrator", "report", "e2e"}
    assert {case["id"] for kind_cases in cases.values() for case in kind_cases} == {
        "expert-niger-coup-v1",
        "orchestrator-dune-follow-up-v1",
        "report-vilnius-summit-v1",
        "e2e-finland-sweden-v1",
    }


class _StubGraph:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self._results = list(results)
        self.calls: list[Any] = []

    async def ainvoke(self, state: Any, config: object = None) -> dict[str, Any]:
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
                    HumanMessage(
                        "Finland research citing [BBC](https://www.bbc.com/x)"
                    ),
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
    assert [message.content for message in stub.calls[0]["messages"]] == [
        "Why Finland?"
    ]
    assert [message.content for message in stub.calls[1]["messages"]] == [
        "What about Sweden?"
    ]
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
        asyncio.run(
            runner.run_e2e({"turns": [{"resume": "approve", "expect": "report"}]})
        )
    assert builds == []


def test_run_e2e_rejects_an_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    builds, stub = _patch_build_graph(monkeypatch, [])
    runner = _load_runner()
    with pytest.raises(ValueError, match="must not be empty"):
        asyncio.run(runner.run_e2e({"turns": [{"query": "   "}]}))
    assert stub.calls == []


def test_run_e2e_rejects_a_non_string_query(monkeypatch: pytest.MonkeyPatch) -> None:
    builds, stub = _patch_build_graph(monkeypatch, [])
    runner = _load_runner()
    with pytest.raises(AttributeError):
        asyncio.run(runner.run_e2e({"turns": [{"query": 5}]}))
    assert stub.calls == []


def test_run_e2e_setup_turn_misroute_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_build_graph(monkeypatch, [{"destination": "other"}])
    runner = _load_runner()
    with pytest.raises(
        RuntimeError, match=r"routed to 'other', expected 'geopolitical'"
    ):
        asyncio.run(
            runner.run_e2e({"turns": [{"query": "q", "expect": "geopolitical"}]})
        )


def test_run_e2e_unknown_expect_rejects_before_any_graph_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    builds, stub = _patch_build_graph(monkeypatch, [])
    runner = _load_runner()
    with pytest.raises(ValueError, match="unknown expected destination"):
        asyncio.run(runner.run_e2e({"turns": [{"query": "q", "expect": "atlantis"}]}))
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


def test_validate_evaluations_accepts_a_kind_with_two_cases() -> None:
    runner = _load_runner()
    names = ("route_correct", "rewrite_quality", "usefulness")
    runs = [
        SimpleNamespace(
            name=name,
            error=None,
            result={
                "score": 1.0 if name == "route_correct" else 4.0,
                "label": "4",
                "explanation": "because",
            },
        )
        for _case_index in range(2)
        for name in names
    ]
    result = {"evaluation_runs": runs}
    outcome = runner.validate_evaluations(
        result, kind_name="e2e", kind_cases=[{}, {}], expected_names=set(names)
    )
    assert outcome.failed == []
    assert outcome.judge_errors == 0
    assert outcome.scored == 6
