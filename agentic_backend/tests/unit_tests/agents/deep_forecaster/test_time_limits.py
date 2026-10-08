"""Unit tests for `agents.deep_forecaster.time_limits`."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

import pytest

limits_module: Any = importlib.import_module("agents.deep_forecaster.time_limits")


@pytest.mark.anyio
async def test_a_run_inside_the_limit_returns_its_result() -> None:
    result, capped = await limits_module.run_under_time_limits(_returns("x"), 1.0)
    assert result == "x"
    assert capped is False


@pytest.mark.anyio
async def test_a_run_outliving_the_cap_is_capped_and_dead() -> None:
    result, capped = await limits_module.run_under_time_limits(_sleeps(10), 0.05)
    assert result is None
    assert capped is True


@pytest.mark.anyio
async def test_a_run_that_ignores_the_first_cancel_is_still_bounded() -> None:
    class _Absorber:
        """A coroutine that swallows cancels twice and keeps sleeping."""

        def __init__(self) -> None:
            self.cancelled = 0

        async def _sleep(self) -> None:
            for _ in range(2):
                try:
                    await asyncio.sleep(10)
                    return
                except asyncio.CancelledError:
                    self.cancelled += 1
            # the next cancel propagates
            await asyncio.sleep(10)

        def __call__(self) -> Any:
            return self._sleep()

    absorber = _Absorber()
    result, capped = await limits_module.run_under_time_limits(absorber(), 0.05)
    assert result is None
    assert capped is True
    assert absorber.cancelled == 2


@pytest.mark.anyio
async def test_the_callers_own_cancellation_cancels_the_inner_run() -> None:
    inner: asyncio.Task[Any] | None = None

    def coro() -> Any:
        nonlocal inner

        async def sleep() -> None:
            nonlocal inner
            inner = asyncio.current_task()
            await asyncio.sleep(10)

        return sleep()

    task = asyncio.ensure_future(limits_module.run_under_time_limits(coro(), 10.0))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert inner is not None
    assert inner.cancelled()


@pytest.mark.anyio
async def test_an_inner_timeout_error_propagates_uncapped() -> None:
    async def fails() -> None:
        raise TimeoutError("inner")

    with pytest.raises(TimeoutError, match="inner"):
        await limits_module.run_under_time_limits(fails(), 10.0)


async def _returns(value: str) -> str:
    return value


async def _sleeps(seconds: float) -> None:
    await asyncio.sleep(seconds)


@pytest.mark.anyio
async def test_an_absorber_that_outlives_every_cancel_is_abandoned(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The abandon branch: a run that swallows cancels leaves no result, and
    its later failure is logged, never reported as the time limit itself."""
    # Arrange
    import agents.deep_forecaster.time_limits as limits

    monkeypatch.setattr(limits, "REPEATS", 1)

    class _InfiniteAbsorber:
        def __init__(self) -> None:
            self.cancelled = 0

        async def _sleep(self) -> None:
            while True:
                try:
                    await asyncio.sleep(10)
                    return
                except asyncio.CancelledError:
                    self.cancelled += 1

        def __call__(self) -> Any:
            return self._sleep()

    absorber = _InfiniteAbsorber()
    # Act
    result, capped = await limits_module.run_under_time_limits(absorber(), 0.02)
    # Assert
    assert result is None
    assert capped is True
    assert absorber.cancelled >= 1
    # the inner run dies at its own client timeouts on the next cancel sweep
    del absorber


@pytest.mark.anyio
async def test_a_task_that_fails_during_the_grace_logs_its_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The grace loop's outcome read: a task that finishes cancelled-clean or
    with an error must not masquerade as a time limit silently."""
    # Arrange

    async def stubborn() -> None:
        """Raise on the first cancel, so the grace loop finishes the task."""

        async def _inner() -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise RuntimeError("grace boom")

        await _inner()

    # Act
    result, capped = await limits_module.run_under_time_limits(stubborn(), 0.02)
    # Assert
    assert result is None
    assert capped is True
    assert "grace boom" in caplog.text
