"""Unit tests for `evals.reporter_fixed`.

The reporter's graph and its reply classifier are scripted fakes patched onto
the `agents.reporter` package, the names the task imports at call time, so no
model is called. Each script raises when it runs out, so an extra call fails.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from langgraph.types import Command

from agents.reporter import ResumeIntent
from agents.reporter.consts.messages import (
    CANCELLED_NOTICE,
    NO_MATERIAL_NOTICE,
    REVISION_CAP_NOTICE,
)
from evals.reporter_fixed import read_outcome, run_reporter_fixed

RESEARCHED = [
    {"role": "user", "content": "What did NATO agree?"},
    {"role": "assistant", "content": "A [5% target](https://news.example/a)."},
    {"role": "user", "content": "Write me a report on that"},
]
GREETING_ONLY = [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hello! How can I help?"},
    {"role": "user", "content": "Write me a report on that"},
]
OUTLINE = ["Target", "Funding"]


class ScriptedGraph:
    """A reporter graph that says, after each invoke, whether the outline still waits."""

    def __init__(self, waiting_after_each_call: list[bool], result: dict[str, Any]):
        self.waiting_after_each_call = waiting_after_each_call
        self.result = result
        self.inputs: list[Any] = []

    async def ainvoke(self, input: Any, config: Any) -> dict[str, Any]:
        if len(self.inputs) >= len(self.waiting_after_each_call):
            raise AssertionError("the graph was invoked more often than scripted")
        self.inputs.append(input)
        return self.result

    async def aget_state(self, config: Any) -> Any:
        waiting = self.waiting_after_each_call[len(self.inputs) - 1]
        interrupts = [SimpleNamespace(value={"outline": OUTLINE})] if waiting else []
        return SimpleNamespace(interrupts=interrupts)

    def resumes(self) -> list[Any]:
        return [item.resume for item in self.inputs if isinstance(item, Command)]


class ScriptedIntents:
    """A reply classifier that returns its intents in order and raises when spent."""

    def __init__(self, intents: list[ResumeIntent]) -> None:
        self.intents = list(intents)
        self.replies: list[str] = []

    async def __call__(self, reply: str, pause: dict[str, Any]) -> ResumeIntent:
        if not self.intents:
            raise AssertionError(
                f"reply {reply!r} was classified, but none was scripted"
            )
        self.replies.append(reply)
        return self.intents.pop(0)


def _result(**overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"outline": OUTLINE, "notice": "", "report": ""}
    result.update(overrides)
    return result


def _run_with(graph: ScriptedGraph, intents: ScriptedIntents) -> Any:
    patches = (
        patch("agents.reporter.build_graph", return_value=graph),
        patch("agents.reporter.classify_resume_intent", intents),
    )
    return patches


@pytest.mark.parametrize(
    ("result", "paused", "outcome"),
    [
        (_result(), True, "open"),
        (_result(report="# Report"), False, "report"),
        (_result(notice=CANCELLED_NOTICE), False, "cancelled"),
        (_result(notice=REVISION_CAP_NOTICE), False, "capped"),
        (_result(notice="No material for that."), False, "refused"),
    ],
    ids=["paused", "report text", "cancel notice", "revision cap", "another notice"],
)
def test_a_report_run_ending_is_named(
    result: dict[str, Any], paused: bool, outcome: str
) -> None:
    # Act
    named = read_outcome(result, paused=paused)

    # Assert
    assert named == outcome


@pytest.mark.anyio
async def test_a_thread_without_research_is_refused_without_a_model_call() -> None:
    # Arrange
    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a model path was reached")

    # Act
    with (
        patch("agents.reporter.build_graph", fail),
        patch("agents.reporter.classify_resume_intent", fail),
    ):
        output = await run_reporter_fixed({"messages": GREETING_ONLY, "replies": ["x"]})

    # Assert
    assert output["outcome"] == "refused"
    assert output["reply_actions"] == []
    assert output["notice"] == NO_MATERIAL_NOTICE


@pytest.mark.anyio
async def test_each_reply_resumes_the_outline_with_its_action_and_instruction() -> None:
    # Arrange: the outline pauses at the start and again after the revision.
    graph = ScriptedGraph([True, True, False], _result(notice=CANCELLED_NOTICE))
    intents = ScriptedIntents(
        [
            ResumeIntent(action="revise", instruction="no"),
            ResumeIntent(action="cancel", instruction=""),
        ]
    )
    first_patch, second_patch = _run_with(graph, intents)

    # Act
    with first_patch, second_patch:
        output = await run_reporter_fixed(
            {"messages": RESEARCHED, "replies": ["no", "never mind"]}
        )

    # Assert
    assert graph.resumes() == [
        {"action": "revise", "instruction": "no"},
        {"action": "cancel", "instruction": ""},
    ]
    assert output["reply_actions"] == ["revise", "cancel"]
    assert output["outcome"] == "cancelled"


@pytest.mark.anyio
async def test_a_reply_read_as_a_new_question_stops_the_replies() -> None:
    # Arrange: only one intent is scripted; classifying the second reply raises.
    graph = ScriptedGraph([True], _result())
    intents = ScriptedIntents([ResumeIntent(action="new_question", instruction="")])
    first_patch, second_patch = _run_with(graph, intents)

    # Act
    with first_patch, second_patch:
        output = await run_reporter_fixed(
            {"messages": RESEARCHED, "replies": ["Who won?", "Looks good"]}
        )

    # Assert
    assert graph.resumes() == []
    assert intents.replies == ["Who won?"]
    assert output["reply_actions"] == ["new_question"]
    assert output["outcome"] == "open"


@pytest.mark.anyio
async def test_a_reply_typed_after_the_outline_stopped_waiting_is_not_sent() -> None:
    # Arrange: the first resume writes the report, so nothing waits for the second reply.
    graph = ScriptedGraph([True, False], _result(report="# Report"))
    intents = ScriptedIntents([ResumeIntent(action="approve", instruction="")])
    first_patch, second_patch = _run_with(graph, intents)

    # Act
    with first_patch, second_patch:
        output = await run_reporter_fixed(
            {"messages": RESEARCHED, "replies": ["Looks good", "Thanks!"]}
        )

    # Assert
    assert output["reply_actions"] == ["approve"]
    assert intents.replies == ["Looks good"]
    assert output["outcome"] == "report"
