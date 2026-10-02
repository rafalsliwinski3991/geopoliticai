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
    # Arrange: a recorder of (seat, model, max_retries); one model raises.
    recorded: list[tuple[str, str, int]] = []
    failing = "inclusionai/ling-3.0-flash-sante:free"

    class FakeClient:
        def __init__(self, seat: str, model: str, max_retries: int) -> None:
            self.seat = seat
            self.model = model
            self.max_retries = max_retries

        async def ainvoke(self, messages: Any) -> Any:
            recorded.append((self.seat, self.model, self.max_retries))
            if self.model == failing:
                raise RuntimeError("dead")
            return type("R", (), {"text": "I do not know how this turned out."})()

    def fake_client(seat: Any, model: str, *, max_retries: int = 2) -> FakeClient:
        return FakeClient(str(seat.model), model, max_retries)

    monkeypatch.setattr(council_module, "member_client", fake_client)
    # Act
    probe = asyncio.run(backtest_module.leak_probe("Will it happen?"))
    # Assert
    lines = probe.split("\n\n")
    member_lines = [line for line in lines if line.startswith("Member ")]
    fallback_lines = [
        line for line in lines if line.startswith("Member ") and "(fallback)" in line
    ]
    plain_lines = [line for line in member_lines if "(fallback)" not in line]
    assert len(plain_lines) == 7
    assert len(fallback_lines) == 5
    assert "unavailable (RuntimeError)" in probe
    assert all(call[2] == 2 for call in recorded)


def test_the_leak_probe_prompt_demands_ignorance() -> None:
    # Assert
    assert "no sources" in backtest_module.LEAK_PROBE_PROMPT
    assert "I do not know how this turned out" in backtest_module.LEAK_PROBE_PROMPT
