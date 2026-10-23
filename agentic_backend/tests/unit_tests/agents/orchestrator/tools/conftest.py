"""Test fixtures and fakes for specialist tools."""

from __future__ import annotations

from typing import Any

from langgraph.prebuilt import ToolRuntime


def make_tool_runtime(
    state: dict[str, Any] | None = None,
    tool_call_id: str = "test_tool_call_id",
    writer: Any = None,
    store: Any = None,
) -> ToolRuntime[Any, Any]:
    """Build a ToolRuntime for testing specialist @tools."""
    return ToolRuntime(
        state=state if state is not None else {"messages": []},
        context={},
        config={},
        stream_writer=writer or (lambda _: None),
        tool_call_id=tool_call_id,
        store=store,
    )
