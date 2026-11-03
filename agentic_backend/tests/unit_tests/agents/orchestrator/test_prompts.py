"""Tests for the orchestrator's prompts."""

import pytest

from agents.orchestrator.prompts import (
    SUPERVISOR_DOCUMENT_PROMPT,
    SUPERVISOR_SYSTEM_PROMPT,
)


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
        "English and Polish",
        "other than English or Polish",
        "whatever the earlier turns were",
        "never in Polish, even when the earlier turns and replies were Polish",
        "search_query",
    ],
)
def test_supervisor_prompt_keeps_its_rules(rule: str) -> None:
    # Arrange
    prompt = SUPERVISOR_SYSTEM_PROMPT

    # Act
    kept = rule in prompt

    # Assert
    assert kept is True


def test_the_document_prompt_names_only_the_document_tool() -> None:
    """A research tool named here would invite a call the document thread cannot run."""
    # Arrange
    research_tools = (
        "run_expert",
        "run_deep_expert",
        "run_deep_forecaster",
        "run_reporter",
    )

    # Act
    named = [tool for tool in research_tools if tool in SUPERVISOR_DOCUMENT_PROMPT]

    # Assert
    assert named == []
    assert "run_document" in SUPERVISOR_DOCUMENT_PROMPT


def test_the_document_prompt_keeps_the_language_rule() -> None:
    """The refusal for other languages holds in a document thread too."""
    # Arrange
    rule = "other than English or Polish"

    # Act
    kept = rule in SUPERVISOR_DOCUMENT_PROMPT

    # Assert
    assert kept is True


def test_the_document_prompt_passes_the_message_unchanged() -> None:
    """The document agent rewrites the question itself; a supervisor rewrite would lose its wording."""
    # Arrange
    rule = "exactly as written"

    # Act
    kept = rule in SUPERVISOR_DOCUMENT_PROMPT

    # Assert
    assert kept is True


def test_the_document_prompt_sends_a_greeting_with_a_question_to_the_document() -> None:
    """The message "hej, o czym jest ten dokument" got the canned greeting because it began with "hej"."""
    # Arrange
    rule = "even when it starts with a greeting"

    # Act
    kept = rule in SUPERVISOR_DOCUMENT_PROMPT

    # Assert
    assert kept is True


def test_the_document_prompt_answers_directly_only_to_a_message_with_no_question() -> (
    None
):
    """The direct answer is for a bare greeting or thanks, never for a message that also asks about the document."""
    # Arrange
    rule = "holds no question about the document"

    # Act
    kept = rule in SUPERVISOR_DOCUMENT_PROMPT

    # Assert
    assert kept is True
