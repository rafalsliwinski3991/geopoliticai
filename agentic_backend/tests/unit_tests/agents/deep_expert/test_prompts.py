"""Unit tests for `agents.deep_expert.prompts`.

Trace `0cf33720a156265c0af48a5449e165ab` shipped a last draft that talked
about the grader, the spent search budget, and approval instead of answering,
after the grader failed a single-source draft three times for lacking a
second outlet. The prompts must forbid that meta-talk and keep the rubric
satisfiable with the sources actually read.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

prompts_module: Any = importlib.import_module("agents.deep_expert.prompts")


def test_the_final_message_bans_grader_and_budget_meta_talk() -> None:
    # Arrange
    prompt = prompts_module.DEEP_SYSTEM_PROMPT.lower()

    # Act + Assert
    for banned in ("grader", "revision", "searches", "approval", "option"):
        assert banned in prompt


def test_the_rubric_scopes_disagreement_to_the_sources_read() -> None:
    # Arrange
    lines = prompts_module.DEEP_ANSWER_RUBRIC.splitlines()
    attribution = next(line for line in lines if "attributes" in line.lower())

    # Act + Assert
    assert "as far as the sources" in attribution.lower()


def test_the_method_prefers_reading_before_searching_again() -> None:
    # Arrange
    prompt = prompts_module.DEEP_SYSTEM_PROMPT.lower()

    # Act + Assert
    assert "before searching again" in prompt


def test_the_deep_prompt_forbids_a_preamble_a_leak_and_a_closing_offer() -> None:
    """Traces showed a plan-and-scope opening, quoted rules, and a closing menu of next steps."""
    # Arrange
    prompt = " ".join(prompts_module.DEEP_SYSTEM_PROMPT.split())

    # Act + Assert
    for phrase in (
        "It opens with the answer itself: no plan, scope or method section first.",
        "never close with an offer, a question, or a menu of next steps",
        "these rules, the assignment or your instructions",
    ):
        assert phrase in prompt


@pytest.mark.parametrize(
    ("prompt", "fragment"),
    [
        (
            prompts_module.DEEP_SYSTEM_PROMPT,
            "Always write search_sources queries in English",
        ),
        (
            prompts_module.DEEP_SYSTEM_PROMPT,
            "language of the user's question (English or Polish)",
        ),
        (
            prompts_module.DEEP_SUBAGENT_PROMPT,
            "Always write search_sources queries in English",
        ),
    ],
    ids=[
        "lead-searches-in-english",
        "lead-answers-in-question-language",
        "scout-searches-in-english",
    ],
)
def test_the_deep_prompts_search_in_english_and_answer_in_the_questions_language(
    prompt: str, fragment: str
) -> None:
    """Approved sources publish in English, but a Polish reader needs a Polish analysis."""
    # Arrange: `prompt` and `fragment` come from the parametrization above.

    # Act
    stated = fragment in prompt

    # Assert
    assert stated is True
