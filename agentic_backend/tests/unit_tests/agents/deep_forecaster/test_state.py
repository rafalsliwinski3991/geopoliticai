"""Unit tests for `agents.deep_forecaster.state`."""

from __future__ import annotations

import asyncio
import dataclasses
import logging

import pytest

from agents.deep_forecaster import state as state_module
from agents.deep_forecaster.config import LIMITS
from agents.deep_forecaster.consts.progress import RESEARCH_LABEL
from agents.deep_forecaster.state import ForecastRun, ResearchRun
from models import Candidate, Source


def _limits_with(**changes: int) -> object:
    """Return a `ForecastLimits` with some fields changed (dataclasses.replace)."""
    return dataclasses.replace(LIMITS, **changes)


def test_has_room_counts_reads_in_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(state_module, "LIMITS", _limits_with(max_sources=2))
    run = ResearchRun(writer=lambda event: None)
    run.sources["https://a.example/1"] = Source("t", "https://a.example/1", "text")
    run.reserved = 1
    assert not run.has_room()
    run.reserved = 0
    assert run.has_room()
    run.sources["https://a.example/2"] = Source("t", "https://a.example/2", "text")
    assert not run.has_room()


def test_lock_for_returns_one_lock_per_url() -> None:
    run = ResearchRun(writer=lambda event: None)
    first = run.lock_for("https://a.example/1")
    assert run.lock_for("https://a.example/1") is first
    assert run.lock_for("https://a.example/2") is not first


def test_enter_records_logs_and_announces_the_step(
    caplog: pytest.LogCaptureFixture,
    events: list[dict[str, object]],
) -> None:
    run = ForecastRun()
    with caplog.at_level(logging.INFO, logger="agents.deep_forecaster.state"):
        run.enter(RESEARCH_LABEL, events.append)
    assert run.step == "Planning the research"
    assert any(
        "forecast step: Planning the research" in r.message for r in caplog.records
    )
    assert events == [
        {"type": "progress", "node": "deep_forecaster", "label": RESEARCH_LABEL}
    ]


def test_search_gate_is_built_from_the_concurrency_cap() -> None:
    run = ResearchRun(writer=lambda event: None)
    assert run.search_gate._value == LIMITS.search_concurrency


def test_candidates_and_sources_keep_read_order() -> None:
    run = ResearchRun(writer=lambda event: None)
    run.candidates.setdefault(
        "https://a.example/1", Candidate("t1", "https://a.example/1", "a.example")
    )
    run.candidates.setdefault(
        "https://b.example/2", Candidate("t2", "https://b.example/2", "b.example")
    )
    run.sources["https://b.example/2"] = Source("t2", "https://b.example/2", "text")
    run.sources["https://a.example/1"] = Source("t1", "https://a.example/1", "text")
    assert list(run.sources) == ["https://b.example/2", "https://a.example/1"]
    assert isinstance(asyncio.Lock(), asyncio.Lock)
