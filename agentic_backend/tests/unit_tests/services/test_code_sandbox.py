import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import CallToolResult, ErrorData, TextContent

from services import code_sandbox
from shared.errors import SandboxUnavailableError

CODE = "print(1 + 1)"
COMPOSE_URL = "http://mcp-server:8000/mcp"
HOST_URL = "http://127.0.0.1:8100/mcp"
SHORT_TIMEOUT_SECONDS = 0.01
# Fails a test whose call is never bounded, so it cannot hang the suite.
TEST_GUARD_SECONDS = 5.0
FINISHED_RUN = {
    "outcome": "ok",
    "stdout": "2\n",
    "stderr": "",
    "exit_code": 0,
    "truncated": False,
    "duration_ms": 41,
}


class FakeSandbox:
    """Stands in for `MultiServerMCPClient` and for the session it opens.

    Answers each tool call with the next scripted item: a result to return, or an
    exception to raise. With nothing scripted, a call raises. A `hangs` sandbox
    never answers.
    """

    def __init__(
        self, *answers: CallToolResult | Exception, hangs: bool = False
    ) -> None:
        self.answers = list(answers)
        self.hangs = hangs
        self.called = asyncio.Event()
        self.connections: list[dict[str, dict[str, object]]] = []
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, connections: dict[str, dict[str, object]]) -> "FakeSandbox":
        self.connections.append(connections)
        return self

    @asynccontextmanager
    async def session(self, server_name: str) -> AsyncIterator["FakeSandbox"]:
        yield self

    async def call_tool(self, name: str, arguments: dict[str, str]) -> CallToolResult:
        self.calls.append((name, arguments))
        self.called.set()
        if self.hangs:
            await asyncio.Event().wait()
        if not self.answers:
            raise AssertionError("an unscripted sandbox call")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def build_result(structured: dict[str, Any] | None) -> CallToolResult:
    return CallToolResult(content=[], structuredContent=structured, isError=False)


def install_sandbox(
    monkeypatch: pytest.MonkeyPatch, sandbox: FakeSandbox
) -> FakeSandbox:
    monkeypatch.setattr(code_sandbox, "MultiServerMCPClient", sandbox)
    return sandbox


@pytest.mark.anyio
async def test_a_finished_run_becomes_a_code_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller reads what the code printed from these fields; one lost or
    swapped on the way would put wrong numbers in an answer."""
    # Arrange
    sandbox = install_sandbox(monkeypatch, FakeSandbox(build_result(FINISHED_RUN)))

    # Act
    run = await code_sandbox.run_code(CODE)

    # Assert
    assert run == code_sandbox.CodeRun(
        outcome="ok",
        stdout="2\n",
        stderr="",
        exit_code=0,
        truncated=False,
        duration_ms=41,
    )
    assert sandbox.calls == [("run_python", {"code": CODE})]


@pytest.mark.anyio
async def test_a_refused_run_is_returned_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A busy sandbox or over-long code is something the model can act on, so it
    must not end the turn as an outage."""
    # Arrange
    refusal = {
        "outcome": "refused",
        "stdout": "",
        "stderr": "The sandbox is busy. Try again in a few seconds.",
        "exit_code": None,
        "truncated": False,
        "duration_ms": 0,
    }
    install_sandbox(monkeypatch, FakeSandbox(build_result(refusal)))

    # Act
    run = await code_sandbox.run_code(CODE)

    # Assert
    assert run == code_sandbox.CodeRun(
        outcome="refused",
        stdout="",
        stderr="The sandbox is busy. Try again in a few seconds.",
        exit_code=None,
        truncated=False,
        duration_ms=0,
    )


@pytest.mark.anyio
async def test_a_server_fault_raises_sandbox_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`isError` means the server itself broke. Handing its text to the model as a
    run would let a turn answer with numbers that were never computed."""
    # Arrange
    fault = CallToolResult(
        content=[TextContent(type="text", text="Error executing tool run_python")],
        structuredContent=None,
        isError=True,
    )
    install_sandbox(monkeypatch, FakeSandbox(fault))

    # Act + Assert
    with pytest.raises(
        SandboxUnavailableError, match="The code sandbox is unavailable."
    ):
        await code_sandbox.run_code(CODE)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure",
    [
        ExceptionGroup("unhandled errors", [httpx.ConnectError("refused")]),
        TimeoutError(),
        McpError(ErrorData(code=-32600, message="Session terminated")),
        RuntimeError("Invalid structured content returned by tool run_python"),
    ],
    ids=["refused connection", "timeout", "protocol error", "result fails schema"],
)
async def test_an_unreachable_sandbox_raises_sandbox_unavailable(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    """Each way the transport fails must reach the API as one pipeline error with a
    status, not as a client library's exception."""
    # Arrange
    install_sandbox(monkeypatch, FakeSandbox(failure))

    # Act + Assert
    with pytest.raises(
        SandboxUnavailableError, match="The code sandbox is unavailable."
    ):
        await code_sandbox.run_code(CODE)


@pytest.mark.anyio
async def test_a_call_that_never_answers_raises_sandbox_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without its own time limit, a hung sandbox would hold the turn until the
    deep expert's much longer wall cap."""
    # Arrange
    monkeypatch.setattr(code_sandbox, "CALL_TIMEOUT_SECONDS", SHORT_TIMEOUT_SECONDS)
    install_sandbox(monkeypatch, FakeSandbox(hangs=True))

    # Act + Assert
    async with asyncio.timeout(TEST_GUARD_SECONDS):
        with pytest.raises(SandboxUnavailableError):
            await code_sandbox.run_code(CODE)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "missing",
    ["outcome", "stdout", "stderr", "exit_code", "truncated", "duration_ms"],
)
async def test_a_result_missing_a_field_raises_sandbox_unavailable(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    """A server and client out of step must fail as the sandbox's error, not as a
    `KeyError` the API cannot report."""
    # Arrange
    partial = {key: value for key, value in FINISHED_RUN.items() if key != missing}
    install_sandbox(monkeypatch, FakeSandbox(build_result(partial)))

    # Act + Assert
    with pytest.raises(SandboxUnavailableError, match="no usable result"):
        await code_sandbox.run_code(CODE)


@pytest.mark.anyio
async def test_a_result_without_structured_content_raises_sandbox_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful reply carrying only text has no outcome to trust."""
    # Arrange
    install_sandbox(monkeypatch, FakeSandbox(build_result(None)))

    # Act + Assert
    with pytest.raises(SandboxUnavailableError, match="no usable result"):
        await code_sandbox.run_code(CODE)


@pytest.mark.anyio
async def test_a_cancelled_call_is_not_turned_into_a_pipeline_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deep expert's wall cap cancels the turn; a client that swallowed the
    cancellation would report an outage and keep the capped run alive."""
    # Arrange
    sandbox = install_sandbox(monkeypatch, FakeSandbox(hangs=True))
    call = asyncio.create_task(code_sandbox.run_code(CODE))
    async with asyncio.timeout(TEST_GUARD_SECONDS):
        await sandbox.called.wait()

    # Act
    call.cancel()

    # Assert
    with pytest.raises(asyncio.CancelledError):
        await call


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("configured", "expected"),
    [(HOST_URL, HOST_URL), (None, COMPOSE_URL), ("", COMPOSE_URL)],
    ids=["variable set", "variable unset", "variable empty"],
)
async def test_the_sandbox_url_comes_from_the_environment_with_a_compose_default(
    monkeypatch: pytest.MonkeyPatch, configured: str | None, expected: str
) -> None:
    """A host run reaches the sandbox through the published port; inside Compose
    nothing has to be configured."""
    # Arrange
    if configured is None:
        monkeypatch.delenv("SANDBOX_MCP_URL", raising=False)
    else:
        monkeypatch.setenv("SANDBOX_MCP_URL", configured)
    sandbox = install_sandbox(monkeypatch, FakeSandbox(build_result(FINISHED_RUN)))

    # Act
    await code_sandbox.run_code(CODE)

    # Assert
    assert [connection["sandbox"]["url"] for connection in sandbox.connections] == [
        expected
    ]
