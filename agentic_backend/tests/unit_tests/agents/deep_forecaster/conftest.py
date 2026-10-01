"""Shared fakes for the deep forecaster's tests; grows per unit."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agents.deep_forecaster.state import ForecastRun


@pytest.fixture
def events() -> list[dict[str, Any]]:
    """Progress frames the run's writer appends to."""
    return []


def runtime(events: list[dict[str, Any]]) -> SimpleNamespace:
    """Return a stand-in for the graph's `Runtime`."""
    return SimpleNamespace(context=ForecastRun(), stream_writer=events.append)
