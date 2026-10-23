"""Unit tests for the deep forecaster specialist tool."""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from langchain_core.messages import ToolMessage

from agents.orchestrator.tools.deep_forecaster import run_deep_forecaster
from unit_tests.agents.orchestrator.tools.conftest import make_tool_runtime

deep_forecaster_tool_module = importlib.import_module(
    "agents.orchestrator.tools.deep_forecaster"
)


class FakeStore:
    """Fake BaseStore for testing runtime store forwarding."""

    def __init__(self) -> None:
        self.accessed = True


@pytest.mark.anyio
async def test_run_deep_forecaster_passes_store_emits_notice_and_updates_forecast_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Delphi forecasting requires runtime.store for its video cache; the tool must forward
    the store, emit the verdict notice, and record the question and summary in forecast_data.
    """
    # Arrange
    emitted_events: list[dict[str, Any]] = []
    forecast_calls: list[tuple[str, Any]] = []
    forecast_verdict = "70% probability of accession by 2028."
    fake_store = FakeStore()

    async def fake_forecast(question: str, store: Any) -> str:
        forecast_calls.append((question, store))
        return forecast_verdict

    monkeypatch.setattr(deep_forecaster_tool_module, "forecast", fake_forecast)

    initial_state = {
        "messages": [],
        "forecast_data": [
            {"question": "Earlier question?", "summary": "40% probability."},
        ],
    }
    runtime = make_tool_runtime(
        state=initial_state,
        tool_call_id="call_forecaster_789",
        writer=emitted_events.append,
        store=fake_store,
    )

    # Act
    command = await run_deep_forecaster.ainvoke(
        {"question": "Will country join alliance?", "runtime": runtime}
    )

    # Assert
    assert forecast_calls == [("Will country join alliance?", fake_store)]
    assert emitted_events == [{"type": "notice", "text": forecast_verdict}]

    update = command.update
    assert update["forecast_data"] == [
        {"question": "Earlier question?", "summary": "40% probability."},
        {"question": "Will country join alliance?", "summary": forecast_verdict},
    ]
    assert len(update["messages"]) == 1
    message = update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.tool_call_id == "call_forecaster_789"
    assert (
        message.content == "Delphi forecast on 'Will country join alliance?' completed."
    )
    assert message.artifact == {"text": forecast_verdict}


@pytest.mark.anyio
async def test_run_deep_forecaster_handles_empty_initial_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When forecast_data is not present in initial state, run_deep_forecaster initializes
    the list without error.
    """
    # Arrange
    forecast_verdict = "50% probability."

    async def fake_forecast(question: str, store: Any) -> str:
        return forecast_verdict

    monkeypatch.setattr(deep_forecaster_tool_module, "forecast", fake_forecast)

    runtime = make_tool_runtime(
        state={"messages": []},
        tool_call_id="call_empty_fc",
    )

    # Act
    command = await run_deep_forecaster.ainvoke(
        {"question": "Will event happen?", "runtime": runtime}
    )

    # Assert
    update = command.update
    assert update["forecast_data"] == [
        {"question": "Will event happen?", "summary": forecast_verdict}
    ]
    assert update["messages"][0].artifact == {"text": forecast_verdict}
