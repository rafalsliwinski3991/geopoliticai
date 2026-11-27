"""The started server, as seen by a peer on its network and by its own runs.

They need the runtime image running as `mcp-server`, with its own `CMD` and the
sandbox's run flags, and run in a second container on the same network
(CLAUDE.md, Commands).
"""

import socket
import time

import httpx
import pytest
from mcp import Client

SERVER_URL = "http://mcp-server:8000"
SERVER_START_SECONDS = 20.0
SLOT_UID = 10010
FORGED_PEER = "192.0.2.10"
# Run by `run_python`, so a slot user inside the server's own container makes the
# request. A `tools/list` needs no run slot, which the calling run holds.
CALL_THE_SERVER = """
import http.client

source = SOURCE and (SOURCE, 0)
connection = http.client.HTTPConnection(TARGET, 8000, timeout=3, source_address=source)
headers = {
    "Host": "localhost:8000",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    **EXTRA_HEADERS,
}
body = '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
connection.request(METHOD, PATH, body=body, headers=headers)
print(connection.getresponse().status)
"""


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module", autouse=True)
def wait_for_server() -> None:
    deadline = time.monotonic() + SERVER_START_SECONDS
    while True:
        try:
            httpx.get(f"{SERVER_URL}/health", trust_env=False).raise_for_status()
            return
        except httpx.TransportError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)


async def run_on_the_server(code: str) -> str:
    """Run `code` through the server and return what it printed."""
    async with Client(f"{SERVER_URL}/mcp") as client:
        result = await client.call_tool("run_python", {"code": code})
    assert result.structured_content is not None, result.content
    assert result.structured_content["outcome"] == "ok", result.structured_content
    return str(result.structured_content["stdout"])


async def call_from_a_run(
    *,
    target: str = "127.0.0.1",
    source: str | None = None,
    method: str = "POST",
    path: str = "/mcp",
    headers: dict[str, str] | None = None,
) -> str:
    """The status the server gives a request that one of its own runs makes."""
    settings = (
        f"TARGET, SOURCE = {target!r}, {source!r}\n"
        f"METHOD, PATH, EXTRA_HEADERS = {method!r}, {path!r}, {headers or {}!r}\n"
    )
    return await run_on_the_server(settings + CALL_THE_SERVER)


@pytest.mark.anyio
async def test_the_started_server_runs_code_as_the_slot_user() -> None:
    """uvloop, which `uvicorn[standard]` brings, cannot start a process as another user."""
    # Arrange
    code = "import os; print(os.getuid())"

    # Act
    stdout = await run_on_the_server(code)

    # Assert
    assert stdout == f"{SLOT_UID}\n"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "request_settings",
    [
        {},
        {"source": "127.0.0.2"},
        {"headers": {"X-Forwarded-For": FORGED_PEER}},
    ],
    ids=["over loopback", "from another loopback address", "forging its address"],
)
async def test_a_run_cannot_call_the_server_back(
    request_settings: dict[str, object],
) -> None:
    """A run that queued another run would chain them past the end of its own."""
    # Act
    status = await call_from_a_run(**request_settings)  # type: ignore[arg-type]

    # Assert
    assert status == "403\n"


@pytest.mark.anyio
async def test_a_run_cannot_call_the_server_back_on_its_network_address() -> None:
    """The server listens on every address, and each of them is open to its runs."""
    # Arrange
    own_address = socket.gethostbyname("mcp-server")

    # Act
    status = await call_from_a_run(target=own_address)

    # Assert
    assert not own_address.startswith("127.")
    assert status == "403\n"


@pytest.mark.anyio
async def test_a_run_may_still_read_health() -> None:
    """The healthcheck comes from inside the container, as a run's requests do."""
    # Act
    status = await call_from_a_run(method="GET", path="/health")

    # Assert
    assert status == "200\n"
