"""Unit tests for `agents.deep_forecaster.caps`."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

import pytest

caps_module: Any = importlib.import_module("agents.deep_forecaster.caps")


@pytest.mark.anyio
async def test_a_run_inside_the_cap_returns_its_result() -> None:
    result, capped = await caps_module.run_under_cap(_returns("x"), 1.0)
    assert result == "x"
    assert capped is False


@pytest.mark.anyio
async def test_a_run_outliving_the_cap_is_capped_and_dead() -> None:
    result, capped = await caps_module.run_under_cap(_sleeps(10), 0.05)
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
    result, capped = await caps_module.run_under_cap(absorber(), 0.05)
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

    task = asyncio.ensure_future(caps_module.run_under_cap(coro(), 10.0))
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
        await caps_module.run_under_cap(fails(), 10.0)


async def _returns(value: str) -> str:
    return value


async def _sleeps(seconds: float) -> None:
    await asyncio.sleep(seconds)
