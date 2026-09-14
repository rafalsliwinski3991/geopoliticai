"""Dataset-loading checks for the manual orchestrator evaluation runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

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
