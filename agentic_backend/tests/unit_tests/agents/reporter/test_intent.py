import importlib
from typing import Any, cast

import pytest

from agents.reporter.state import ResumeAction, ResumeIntent

node_module = importlib.import_module("agents.reporter.intent")


def _stub_intent(
    monkeypatch: pytest.MonkeyPatch, action: ResumeAction, instruction: str
) -> None:
    async def decide(
        prompt: str,
        messages: list[Any],
        schema: Any,
        *,
        config: Any = None,
        settings: Any = None,
    ) -> ResumeIntent:
        return ResumeIntent(action=action, instruction=instruction)

    monkeypatch.setattr(node_module, "ainvoke_structured", decide)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("action", "instruction"),
    [
        ("approve", ""),
        ("cancel", ""),
        ("new_question", ""),
        ("revise", "  drop the  Poland section  "),
    ],
)
async def test_each_action_round_trips_with_a_normalized_instruction(
    monkeypatch: pytest.MonkeyPatch, action: str, instruction: str
) -> None:
    # Arrange
    _stub_intent(monkeypatch, cast(ResumeAction, action), instruction)

    # Act
    result = await node_module.classify_resume_intent(
        "some line", {"outline": ["First", "Second"]}
    )

    # Assert
    expected_instruction = "drop the Poland section" if action == "revise" else ""
    assert result == ResumeIntent(
        action=cast(ResumeAction, action), instruction=expected_instruction
    )


@pytest.mark.anyio
async def test_a_revise_with_an_empty_instruction_falls_back_to_the_users_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    _stub_intent(monkeypatch, "revise", "   ")

    # Act
    result = await node_module.classify_resume_intent(
        "  Add   Poland  ", {"outline": ["First"]}
    )

    # Assert
    assert result == ResumeIntent(action="revise", instruction="Add Poland")
