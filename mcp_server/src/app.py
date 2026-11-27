"""The sandbox's HTTP app: FastAPI serves `/health` and hosts the MCP server at `/mcp`.

Runs share the server's container, so `LocalPeerGate` answers that container
nothing but `GET /health`.

`create_app()` builds a fresh `MCPServer` each time: its session manager can be
started only once per instance, and tests need one per app. The server is kept on
`app.state.mcp`, where tests connect to it in-process.
"""

from __future__ import annotations

import asyncio
import errno
import ipaddress
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from ipaddress import IPv4Address, IPv6Address

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from config import ALLOWED_HOSTS, LIMITS, SLOT_USERS
from runner import RunResult, run_code

CODE_TOO_LONG_MESSAGE = (
    f"The code is longer than {LIMITS.code_bytes} bytes. Shorten it."
)
BUSY_MESSAGE = "The sandbox is busy. Try again in a few seconds."
# All the server answers to its own container, where its runs and the healthcheck
# are.
LOCAL_REQUESTS = (("GET", "/health"),)
LOCAL_REFUSAL_MESSAGE = "This server answers only GET /health to its own container."


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


def bind_to(address: IPv4Address | IPv6Address) -> None:
    """Bind a throwaway socket to `address`; the kernel allows only its own."""
    family = socket.AF_INET if address.version == 4 else socket.AF_INET6
    with socket.socket(family, socket.SOCK_DGRAM) as probe:
        probe.bind((str(address), 0))


def is_local_address(host: str) -> bool:
    """Whether `host` is this machine; an address that cannot be checked counts as it."""
    try:
        address = ipaddress.ip_address(host)
        if isinstance(address, IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        if address.is_loopback:
            return True
        bind_to(address)
    except ValueError:
        return True
    except OSError as error:
        return error.errno != errno.EADDRNOTAVAIL
    return True


class LocalPeerGate:
    """Refuse the server's own container everything but `LOCAL_REQUESTS`.

    A run is in that container too: one that could call `/mcp` could queue a run
    that starts after the sweep, and chain runs without limit. The peer address
    must be the socket's own, so uvicorn runs with `--no-proxy-headers`; by
    default it lets 127.0.0.1 replace it with `X-Forwarded-For`.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "lifespan":
            request = (scope.get("method"), scope["path"])
            peer = scope.get("client")
            if request not in LOCAL_REQUESTS and (
                peer is None or is_local_address(peer[0])
            ):
                refusal = PlainTextResponse(LOCAL_REFUSAL_MESSAGE, status_code=403)
                await refusal(scope, receive, send)
                return
        await self.app(scope, receive, send)


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
    # Around the whole app, so a route added later is closed to runs too.
    app.add_middleware(LocalPeerGate)

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
