"""Unit tests for `agents.capped_run`."""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

import pytest
from langgraph.constants import CONFIG_KEY_CHECKPOINTER
from langgraph.errors import NodeTimeoutError

from models import LLMInvocationError, SearchUnavailableError

limits_module: Any = importlib.import_module("agents.capped_run")


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


class _FakeGraph:
    """A graph that records each run, then sleeps, raises, or returns as scripted."""

    def __init__(
        self,
        result: Any = None,
        error: BaseException | None = None,
        sleep_seconds: float = 0.0,
    ) -> None:
        self.result = result
        self.error = error
        self.sleep_seconds = sleep_seconds
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    async def ainvoke(self, graph_input: Any, **kwargs: Any) -> Any:
        self.calls.append((graph_input, kwargs))
        if self.sleep_seconds:
            await asyncio.sleep(self.sleep_seconds)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.anyio
async def test_a_finished_run_returns_its_result() -> None:
    """Callers read the result and the `False` cap flag from one call."""
    # Arrange
    graph = _FakeGraph(result={"answer": "done"})
    # Act
    result, capped = await limits_module.invoke_capped(
        graph, {"question": "q"}, limit_seconds=1.0, failure="The run failed."
    )
    # Assert
    assert result == {"answer": "done"}
    assert capped is False


@pytest.mark.anyio
async def test_the_run_has_no_checkpointer() -> None:
    """A parent's saver must not reach the tree: the run's config switches it off."""
    # Arrange
    graph = _FakeGraph(result={})
    # Act
    await limits_module.invoke_capped(
        graph, {}, limit_seconds=1.0, failure="The run failed."
    )
    # Assert
    _, kwargs = graph.calls[0]
    assert kwargs["config"] == {"configurable": {CONFIG_KEY_CHECKPOINTER: None}}


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("context", "expected_keys"),
    [(None, {"config"}), ("run", {"config", "context"})],
    ids=["no context given", "a context given"],
)
async def test_context_is_passed_only_when_given(
    context: str | None, expected_keys: set[str]
) -> None:
    """The deep agents take no context; the forecaster's run needs its own."""
    # Arrange
    graph = _FakeGraph(result={})
    # Act
    await limits_module.invoke_capped(
        graph, {}, limit_seconds=1.0, failure="The run failed.", context=context
    )
    # Assert
    _, kwargs = graph.calls[0]
    assert set(kwargs) == expected_keys
    assert kwargs.get("context") == context


@pytest.mark.anyio
async def test_a_pipeline_error_passes_through() -> None:
    """A pipeline error already carries its status, so it is re-raised as is."""
    # Arrange
    graph = _FakeGraph(error=SearchUnavailableError("outage"))
    # Act + Assert
    with pytest.raises(SearchUnavailableError, match="outage"):
        await limits_module.invoke_capped(
            graph, {}, limit_seconds=1.0, failure="The run failed."
        )


@pytest.mark.anyio
async def test_a_node_timeout_passes_through() -> None:
    """A node's own timeout is not a wall cap: the caller words it for its step."""
    # Arrange
    timeout = NodeTimeoutError("draft_claims", 90.5, kind="run", run_timeout=90.0)
    graph = _FakeGraph(error=timeout)
    # Act + Assert
    with pytest.raises(NodeTimeoutError) as raised:
        await limits_module.invoke_capped(
            graph, {}, limit_seconds=1.0, failure="The run failed."
        )
    assert raised.value is timeout


@pytest.mark.anyio
async def test_any_other_error_becomes_the_callers_failure() -> None:
    """An unexpected error reaches the user as a 502 worded for the caller's step."""
    # Arrange
    graph = _FakeGraph(error=RuntimeError("bug"))
    # Act + Assert
    with pytest.raises(LLMInvocationError) as raised:
        await limits_module.invoke_capped(
            graph, {}, limit_seconds=1.0, failure="The run failed."
        )
    assert str(raised.value) == "The run failed."
    assert isinstance(raised.value.__cause__, RuntimeError)


@pytest.mark.anyio
async def test_a_capped_run_returns_no_result() -> None:
    """A run the cap ends has no result; the caller raises its own limit error."""
    # Arrange
    graph = _FakeGraph(result={"answer": "late"}, sleep_seconds=10.0)
    # Act
    result, capped = await limits_module.invoke_capped(
        graph, {}, limit_seconds=0.05, failure="The run failed."
    )
    # Assert
    assert result is None
    assert capped is True


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
    import agents.capped_run as limits

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
