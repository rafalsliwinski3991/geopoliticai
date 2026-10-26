"""Shared fakes for the orchestrator tests."""

from __future__ import annotations

from typing import Any, Optional

from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig


class ScriptedChatModel:
    """Scripted chat model: replies in order, records every prompt, fails when over-called.

    An `Exception` in the script is raised in place of a reply.
    """

    def __init__(self, responses: list[AnyMessage | Exception]) -> None:
        self.responses = list(responses)
        self.invocations: list[list[AnyMessage]] = []

    def bind_tools(self, *args: Any, **kwargs: Any) -> ScriptedChatModel:
        return self

    def with_config(self, *args: Any, **kwargs: Any) -> ScriptedChatModel:
        return self

    async def ainvoke(
        self,
        messages: list[AnyMessage],
        *,
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ) -> AnyMessage:
        self.invocations.append(messages)
        if not self.responses:
            raise AssertionError(
                "ScriptedChatModel exhausted: unexpected model invocation"
            )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response
