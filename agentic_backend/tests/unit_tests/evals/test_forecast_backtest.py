"""Unit tests for `evals.forecast_backtest`."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

import pytest

backtest_module: Any = importlib.import_module("evals.forecast_backtest")
council_module: Any = importlib.import_module("agents.deep_forecaster.council")
config_module: Any = importlib.import_module("agents.deep_forecaster.config")


def test_leak_probe_asks_every_model_that_can_vote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange: a recorder of (seat, model, max_retries); every model answers.
    recorded: list[tuple[str, str, int]] = []

    class FakeClient:
        def __init__(self, seat: str, model: str, max_retries: int) -> None:
            self.seat = seat
            self.model = model
            self.max_retries = max_retries

        async def ainvoke(self, messages: Any) -> Any:
            recorded.append((self.seat, self.model, self.max_retries))
            return type("R", (), {"text": "I do not know how this turned out."})()

    def fake_client(seat: Any, model: str, *, max_retries: int = 2) -> FakeClient:
        return FakeClient(str(seat.model), model, max_retries)

    monkeypatch.setattr(council_module, "member_client", fake_client)
    # Act
    probe = asyncio.run(backtest_module.leak_probe("Will it happen?"))
    # Assert
    lines = probe.split("\n\n")
    member_lines = [line for line in lines if line.startswith("Member ")]
    assert len(member_lines) == 7
    assert all("(fallback)" not in line for line in member_lines)
    assert "unavailable" not in probe
    assert all(call[2] == 2 for call in recorded)


def test_a_probe_failure_makes_the_run_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model that cannot answer at all forbids the run, not a pass (F6): a
    429, a missing key or a retired id would otherwise read as ignorance."""

    # Arrange
    class FakeClient:
        def __init__(self, seat: str, model: str, max_retries: int) -> None:
            self.model = model

        async def ainvoke(self, messages: Any) -> Any:
            raise RuntimeError("dead")

    def fake_client(seat: Any, model: str, *, max_retries: int = 2) -> FakeClient:
        return FakeClient(str(seat.model), model, max_retries)

    monkeypatch.setattr(council_module, "member_client", fake_client)
    # Act + Assert: the raise names the members that could not be reached
    with pytest.raises(backtest_module.ProbeUnavailableError) as refusal:
        asyncio.run(backtest_module.leak_probe("Will it happen?"))
    assert "Member 1" in str(refusal.value)
    assert "unavailable" not in str(refusal.value)


def test_the_leak_probe_prompt_demands_ignorance() -> None:
    # Assert
    assert "no sources" in backtest_module.LEAK_PROBE_PROMPT
    assert "I do not know how this turned out" in backtest_module.LEAK_PROBE_PROMPT
