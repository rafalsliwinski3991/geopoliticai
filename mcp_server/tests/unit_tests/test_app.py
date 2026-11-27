from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
from mcp import Client
from mcp_types import CallToolResult

import app as app_module
from app import create_app
from config import LIMITS
from runner import RunResult

CODE_CAP_BYTES = 20_000
SHORT_QUEUE_SECONDS = 0.1
CANCEL_AFTER_SECONDS = 0.5
FRESH_QUEUE_SECONDS = 2.0
ONE_SLOT: tuple[str | None, ...] = (None,)
RESULT_FIELDS = {
    "outcome",
    "stdout",
    "stderr",
    "exit_code",
    "truncated",
    "duration_ms",
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


class HeldRun:
    """A `run_code` that keeps its slot until the test releases it."""

    def __init__(self) -> None:
        self.started = anyio.Event()
        self.release = anyio.Event()

    async def __call__(self, code: str, *, run_as: str | None) -> RunResult:
        self.started.set()
        await self.release.wait()
        return RunResult(
            outcome="ok",
            stdout="",
            stderr="",
            exit_code=0,
            truncated=False,
            duration_ms=0,
        )


class FailingRun:
    """A `run_code` on a server that cannot switch users."""

    def __init__(self) -> None:
        self.codes: list[str] = []

    async def __call__(self, code: str, *, run_as: str | None) -> RunResult:
        self.codes.append(code)
        raise PermissionError("cannot switch user")


async def run_python(client: Client, code: str) -> CallToolResult:
    return await client.call_tool("run_python", {"code": code})


def read_outcome(result: CallToolResult) -> Any:
    assert result.structured_content is not None, result.content
    return result.structured_content["outcome"]


def pad_to(code: str, total_bytes: int, filler: str) -> str:
    """Append a comment of `filler` so the code is at most `total_bytes` long."""
    room = total_bytes - len(code.encode()) - 1
    return code + "#" + filler * (room // len(filler.encode()))


@asynccontextmanager
async def serve(base_url: str) -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client on a fresh app whose lifespan is running."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as http:
            yield http


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("total_bytes", "filler", "outcome", "ran"),
    [
        (CODE_CAP_BYTES, "x", "ok", True),
        (CODE_CAP_BYTES + 1, "x", "refused", False),
        (CODE_CAP_BYTES + 2, "é", "refused", False),
    ],
    ids=["at the cap", "one byte over", "over in bytes but not in characters"],
)
async def test_code_over_the_size_cap_is_refused_without_running(
    tmp_path: Path, total_bytes: int, filler: str, outcome: str, ran: bool
) -> None:
    """The cap bounds what the server accepts, so it counts bytes before any run."""
    # Arrange
    marker = tmp_path / "ran"
    code = pad_to(f"open({str(marker)!r}, 'w').close()\n", total_bytes, filler)
    app = create_app(slot_users=ONE_SLOT)

    async with Client(app.state.mcp) as client:
        # Act
        result = await run_python(client, code)

    # Assert
    assert read_outcome(result) == outcome
    assert marker.exists() is ran


@pytest.mark.anyio
async def test_a_call_that_cannot_get_a_run_slot_in_time_is_refused_as_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A queued call must end with an answer the model can act on, not hang."""
    # Arrange
    held = HeldRun()
    monkeypatch.setattr(app_module, "run_code", held)
    monkeypatch.setattr(
        app_module, "LIMITS", replace(LIMITS, queue_seconds=SHORT_QUEUE_SECONDS)
    )
    app = create_app(slot_users=ONE_SLOT)

    async with Client(app.state.mcp) as client, anyio.create_task_group() as tasks:
        tasks.start_soon(run_python, client, "first")
        with anyio.fail_after(FRESH_QUEUE_SECONDS):
            await held.started.wait()

        # Act
        with anyio.fail_after(FRESH_QUEUE_SECONDS):
            result = await run_python(client, "second")
        held.release.set()

    # Assert
    assert read_outcome(result) == "refused"
    assert result.structured_content is not None
    assert "busy" in result.structured_content["stderr"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "first_code",
    ["print('fine')", "raise ValueError('broken')"],
    ids=["after a successful run", "after a failing run"],
)
async def test_a_slot_is_returned_after_every_run(
    monkeypatch: pytest.MonkeyPatch, first_code: str
) -> None:
    """A leaked slot would refuse every later call until a restart."""
    # Arrange
    monkeypatch.setattr(
        app_module, "LIMITS", replace(LIMITS, queue_seconds=FRESH_QUEUE_SECONDS)
    )
    app = create_app(slot_users=ONE_SLOT)

    async with Client(app.state.mcp) as client:
        await run_python(client, first_code)

        # Act
        result = await run_python(client, "print('second')")

    # Assert
    assert read_outcome(result) == "ok"


@pytest.mark.anyio
async def test_a_slot_is_returned_after_a_server_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One crash must not leave every later call refused as busy."""
    # Arrange
    failing = FailingRun()
    monkeypatch.setattr(app_module, "run_code", failing)
    monkeypatch.setattr(
        app_module, "LIMITS", replace(LIMITS, queue_seconds=SHORT_QUEUE_SECONDS)
    )
    app = create_app(slot_users=ONE_SLOT)

    async with Client(app.state.mcp) as client:
        await run_python(client, "first")

        # Act
        await run_python(client, "second")

    # Assert
    assert failing.codes == ["first", "second"]


@pytest.mark.anyio
async def test_a_cancelled_call_returns_its_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client that gives up mid-run must not leave the only slot taken."""
    # Arrange
    monkeypatch.setattr(
        app_module, "LIMITS", replace(LIMITS, queue_seconds=FRESH_QUEUE_SECONDS)
    )
    app = create_app(slot_users=ONE_SLOT)

    async with Client(app.state.mcp) as client:
        with anyio.move_on_after(CANCEL_AFTER_SECONDS):
            await run_python(client, "import time; time.sleep(30)")

        # Act
        result = await run_python(client, "print('next')")

    # Assert
    assert read_outcome(result) == "ok"


@pytest.mark.anyio
async def test_run_python_returns_the_run_as_structured_content() -> None:
    """The backend reads these fields by name, not the tool's text."""
    # Arrange
    app = create_app(slot_users=ONE_SLOT)

    async with Client(app.state.mcp) as client:
        # Act
        result = await run_python(client, "print('hi')")

    # Assert
    assert result.is_error is False
    assert result.structured_content is not None
    assert set(result.structured_content) == RESULT_FIELDS
    assert result.structured_content["stdout"] == "hi\n"


@pytest.mark.anyio
async def test_an_unexpected_server_error_is_reported_as_a_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken sandbox must fail closed, not look like a refusal the model retries."""
    # Arrange
    failing = FailingRun()
    monkeypatch.setattr(app_module, "run_code", failing)
    app = create_app(slot_users=ONE_SLOT)

    async with Client(app.state.mcp) as client:
        # Act
        result = await run_python(client, "print('never')")

    # Assert
    assert failing.codes == ["print('never')"]
    assert result.is_error is True
    assert result.structured_content is None


@pytest.mark.anyio
async def test_health_answers_and_the_mounted_mcp_endpoint_accepts_a_handshake() -> (
    None
):
    """Starlette skips a mounted app's lifespan, which would leave `/mcp` dead."""
    # Arrange
    async with serve("http://mcp-server:8000") as http:
        # Act
        health = await http.get("/health")
        handshake = await http.post(
            "/mcp", json=INITIALIZE_REQUEST, headers=MCP_HEADERS
        )

    # Assert
    assert (health.status_code, health.json()) == (200, {"status": "ok"})
    assert handshake.status_code == 200
    assert '"serverInfo"' in handshake.text


@pytest.mark.anyio
async def test_a_request_for_an_unlisted_host_is_rejected() -> None:
    """The Host check blocks DNS rebinding against the sandbox."""
    # Arrange
    async with serve("http://attacker.example") as http:
        # Act
        response = await http.post("/mcp", json=INITIALIZE_REQUEST, headers=MCP_HEADERS)

    # Assert
    assert response.status_code == 421
