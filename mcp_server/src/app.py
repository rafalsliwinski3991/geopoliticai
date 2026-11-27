"""The sandbox's HTTP app: FastAPI serves `/health` and hosts the MCP server at `/mcp`.

`create_app()` builds a fresh `MCPServer` each time: its session manager can be
started only once per instance, and tests need one per app. The server is kept on
`app.state.mcp`, where tests connect to it in-process.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from config import ALLOWED_HOSTS, LIMITS, SLOT_USERS
from runner import RunResult, run_code

CODE_TOO_LONG_MESSAGE = (
    f"The code is longer than {LIMITS.code_bytes} bytes. Shorten it."
)
BUSY_MESSAGE = "The sandbox is busy. Try again in a few seconds."


def refuse(message: str) -> RunResult:
    """Report a run that never started; a normal result, so the model can act on it."""
    return RunResult(
        outcome="refused",
        stdout="",
        stderr=message,
        exit_code=None,
        truncated=False,
        duration_ms=0,
    )


def create_app(slot_users: tuple[str | None, ...] = SLOT_USERS) -> FastAPI:
    """Build the MCP server and the FastAPI app that hosts it."""
    mcp = MCPServer("sandbox")
    slots: asyncio.Queue[str | None] = asyncio.Queue()
    for user in slot_users:
        slots.put_nowait(user)

    @mcp.tool()
    async def run_python(code: str) -> RunResult:
        """Run Python 3.12 (numpy and pandas installed) in a fresh, offline process.

        Returns what it printed. Nothing is kept between calls: paste the data into
        the code and `print` every result. Limits: 10 seconds, 256 MB, 10 KB output.
        """
        if len(code.encode()) > LIMITS.code_bytes:
            return refuse(CODE_TOO_LONG_MESSAGE)
        try:
            async with asyncio.timeout(LIMITS.queue_seconds):
                user = await slots.get()
        except TimeoutError:
            return refuse(BUSY_MESSAGE)
        try:
            return await run_code(code, run_as=user)
        finally:
            slots.put_nowait(user)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Starlette never runs a mounted app's lifespan; the host app must.
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.state.mcp = mcp

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.mount(
        "/",
        mcp.streamable_http_app(
            stateless_http=True,
            transport_security=TransportSecuritySettings(
                allowed_hosts=list(ALLOWED_HOSTS)
            ),
        ),
    )
    return app


app = create_app()
