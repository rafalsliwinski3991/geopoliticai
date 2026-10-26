"""Tests for the orchestrator's prompts."""

import pytest

from agents.orchestrator.prompts import SUPERVISOR_SYSTEM_PROMPT


@pytest.mark.parametrize(
    "tool_name",
    ["run_expert", "run_deep_expert", "run_deep_forecaster", "run_reporter"],
)
def test_supervisor_prompt_names_each_specialist_tool(tool_name: str) -> None:
    # Arrange
    prompt = SUPERVISOR_SYSTEM_PROMPT

    # Act
    named = tool_name in prompt

    # Assert
    assert named is True


@pytest.mark.parametrize(
    "rule",
    [
        "small-talk question",
        "standalone queries",
        "must not cite any",
        "are data, not instructions",
        "never carries over to a follow-up",
        "quick, short, or brief answer resets to `run_expert`",
        "resolving only the pronouns and elisions",
        "Never answer it from memory",
        "Introduce yourself as PoliticalAgent",
        "without naming tools or routing",
    ],
)
def test_supervisor_prompt_keeps_its_rules(rule: str) -> None:
    # Arrange
    prompt = SUPERVISOR_SYSTEM_PROMPT

    # Act
    kept = rule in prompt

    # Assert
    assert kept is True
