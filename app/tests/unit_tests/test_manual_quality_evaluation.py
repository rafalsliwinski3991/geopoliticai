"""Regression checks for the manual Phoenix evaluation runner's UI boundary."""

from __future__ import annotations

import ast
from pathlib import Path

RUNNER_PATH = Path(__file__).parents[1] / "manual_quality" / "basic_agent_evaluation.py"


def test_live_results_use_phoenix_native_output() -> None:
    """Keep result presentation in Phoenix instead of custom terminal rendering."""
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
