"""The isolation rules that only hold inside the image.

They need what the `test` stage's run flags give: root holding three
capabilities, the slot user, a read-only root, no System V IPC or message
queues, and an internal network.
"""

import os
import subprocess
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import anyio
import httpx
import pytest
from mcp import Client
from mcp_types import CallToolResult

import runner
from app import create_app
from config import LIMITS
from runner import RunResult, run_code

SLOT_USER = "sandbox0"
SLOT_UID = 10010
MAX_SLOT_PROCESSES = 64
SHORT_WALL_SECONDS = 2.0
# A stopped run must be back well before its 40 s sleepers would exit by themselves.
PROMPT_SECONDS = 8.0
# How long killed processes may take to be reaped by init.
DEATH_SECONDS = 5.0
SERVER_START_SECONDS = 20.0
SERVER_URL = "http://127.0.0.1:8000"
# The runtime image's `CMD`, bound to loopback.
SERVER_COMMAND = [
    ".venv/bin/uvicorn",
    "app:app",
    "--app-dir",
    "src",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
]
# Starts `DETACHED` in its own session with none of the run's pipes, and waits
# until it is running.
START_DETACHED_CHILD = """
import subprocess, sys
child = subprocess.Popen(
    [sys.executable, "-c", DETACHED],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
)
child.stdout.readline()
print("done")
"""
SLEEPS = """
import os, time
print(flush=True)
os.close(1)
time.sleep(40)
"""
REPLACES_ITSELF = """
import os
print(flush=True)
os.close(1)
while True:
    if os.fork():
        os._exit(0)
"""
# Waits for the run's own process to exit, then signals every process of its user.
SIGNALS_ITS_USER = """
import os, signal
parent = os.getppid()
print(flush=True)
os.close(1)
while os.getppid() == parent:
    pass
while True:
    try:
        os.kill(-1, signal.{name})
    except ProcessLookupError:
        pass
"""


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


def shorten_wall_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner, "LIMITS", replace(LIMITS, wall_seconds=SHORT_WALL_SECONDS)
    )


async def run_as_slot_user(code: str) -> RunResult:
    return await run_code(code, run_as=SLOT_USER)


async def run_python(client: Client, code: str) -> CallToolResult:
    return await client.call_tool("run_python", {"code": code})


def count_slot_processes() -> int:
    count = 0
    for status_file in Path("/proc").glob("[0-9]*/status"):
        try:
            status = status_file.read_text()
        except (FileNotFoundError, ProcessLookupError):
            continue
        fields = dict(line.split(":\t", 1) for line in status.splitlines())
        if int(fields["Uid"].split()[0]) == SLOT_UID and fields["State"][0] != "Z":
            count += 1
    return count


def is_slot_user_idle() -> bool:
    """Ask the kernel about all of the user's processes at once.

    A `/proc` scan would slip past one that keeps forking, and no run can affect
    this call.
    """
    try:
        os.getpriority(os.PRIO_USER, SLOT_UID)
    except ProcessLookupError:
        return True
    return False


async def wait_until(condition: Callable[[], bool], seconds: float) -> bool:
    with anyio.move_on_after(seconds):
        while not condition():
            await anyio.sleep(0.02)
        return True
    return False


@asynccontextmanager
async def start_server() -> AsyncIterator[str]:
    """The real server as its own process, answering `/health`."""
    server = subprocess.Popen(SERVER_COMMAND, cwd="/app")

    def is_ready() -> bool:
        try:
            return httpx.get(f"{SERVER_URL}/health", trust_env=False).is_success
        except httpx.TransportError:
            return False

    try:
        assert await wait_until(is_ready, SERVER_START_SECONDS)
        yield f"{SERVER_URL}/mcp"
    finally:
        server.terminate()
        server.wait(timeout=SERVER_START_SECONDS)


@pytest.mark.anyio
async def test_the_started_server_runs_code_as_the_slot_user() -> None:
    """uvloop, which `uvicorn[standard]` brings, cannot start a process as another user."""
    # Arrange
    async with start_server() as url, Client(url) as client:
        # Act
        result = await run_python(client, "import os; print(os.getuid())")

    # Assert
    assert result.is_error is False, result.content
    assert result.structured_content is not None
    assert result.structured_content["outcome"] == "ok"
    assert result.structured_content["stdout"] == f"{SLOT_UID}\n"


@pytest.mark.anyio
async def test_every_run_executes_as_a_slot_user() -> None:
    """Model-written code must never hold root's identity, groups or capabilities."""
    # Arrange
    code = (
        "import os\n"
        "print(os.getresuid())\n"
        "print(0 in os.getresgid(), os.getgroups())\n"
        "status = open('/proc/self/status').read()\n"
        "print([line.split()[1] for line in status.splitlines()"
        " if line.startswith(('CapPrm', 'CapEff'))])\n"
    )
    app = create_app()

    async with Client(app.state.mcp) as client:
        # Act
        result = await run_python(client, code)

    # Assert
    assert result.structured_content is not None, result.content
    assert result.structured_content["stdout"] == (
        f"({SLOT_UID}, {SLOT_UID}, {SLOT_UID})\n"
        "False []\n"
        "['0000000000000000', '0000000000000000']\n"
    )


@pytest.mark.anyio
async def test_a_run_cannot_signal_the_server() -> None:
    """A run that could kill the server would take the sandbox down for everyone."""
    # Arrange
    code = (
        "import os, signal\n"
        "print(os.getppid(), flush=True)\n"
        "os.kill(os.getppid(), signal.SIGKILL)\n"
    )

    # Act
    result = await run_as_slot_user(code)

    # Assert
    assert result.stdout == f"{os.getpid()}\n"
    assert result.outcome == "error"
    assert "PermissionError" in result.stderr


@pytest.mark.anyio
@pytest.mark.parametrize(
    "directory",
    ["/app", "/tmp", "/dev/shm", "/"],
    ids=["the app", "tmp", "shared memory", "the root"],
)
async def test_a_run_cannot_write_anywhere(directory: str) -> None:
    """A file a run leaves behind would reach the next user's run."""
    # Arrange
    target = Path(directory) / "sandbox-probe"

    # Act
    result = await run_as_slot_user(f"open({str(target)!r}, 'w')")

    # Assert
    assert result.outcome == "error"
    assert (
        "PermissionError" in result.stderr or "Read-only file system" in result.stderr
    )
    assert not target.exists()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("create", "refusal"),
    [
        ("libc.mq_open(b'/leak', os.O_CREAT | os.O_RDWR, 0o600, None)", "ENOSPC"),
        ("libc.shmget(IPC_PRIVATE, 4096, IPC_CREAT | 0o600)", "ENOSPC"),
        ("libc.msgget(IPC_PRIVATE, IPC_CREAT | 0o600)", "ENOSPC"),
        ("libc.semget(IPC_PRIVATE, 1, IPC_CREAT | 0o600)", "EINVAL"),
    ],
    ids=["message queue file", "shared memory", "message queue", "semaphore set"],
)
async def test_a_run_cannot_create_an_ipc_object(create: str, refusal: str) -> None:
    """IPC objects outlive their process, so they would carry state between runs."""
    # Arrange
    code = (
        "import ctypes, errno, os\n"
        "IPC_PRIVATE, IPC_CREAT = 0, 0o1000\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        f"print({create}, errno.errorcode.get(ctypes.get_errno()))\n"
    )

    # Act
    result = await run_as_slot_user(code)

    # Assert
    assert result.stdout == f"-1 {refusal}\n", result.stderr


@pytest.mark.anyio
async def test_a_run_cannot_reach_the_network() -> None:
    """Model-written code must not send data out or fetch anything."""
    # Arrange
    code = "import socket; socket.create_connection(('1.1.1.1', 53), 2)"

    # Act
    result = await run_as_slot_user(code)

    # Assert
    assert result.outcome == "error"
    assert "OSError" in result.stderr or "TimeoutError" in result.stderr


@pytest.mark.anyio
async def test_a_timed_out_run_is_killed_across_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The run belongs to another user, so stopping it takes CAP_KILL."""
    # Arrange
    shorten_wall_limit(monkeypatch)

    # Act
    result = await run_as_slot_user("import time; time.sleep(60)")

    # Assert
    assert result.outcome == "timeout"
    assert await wait_until(is_slot_user_idle, DEATH_SECONDS)


@pytest.mark.anyio
async def test_a_timeout_kills_the_runs_whole_process_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A grandchild left running would hold the slot user into the next run."""
    # Arrange
    shorten_wall_limit(monkeypatch)
    code = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(40)'])\n"
        "time.sleep(40)\n"
    )
    results: list[RunResult] = []

    async def run() -> None:
        results.append(await run_as_slot_user(code))

    # Act
    with anyio.fail_after(PROMPT_SECONDS):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(run)
            started = await wait_until(
                lambda: count_slot_processes() == 2, SHORT_WALL_SECONDS
            )

    # Assert
    assert started
    assert results[0].outcome == "timeout"
    assert await wait_until(is_slot_user_idle, DEATH_SECONDS)


@pytest.mark.anyio
async def test_a_timed_out_run_with_a_child_in_its_own_session_returns_promptly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Such a child escapes the group kill and keeps the pipes, blocking the only slot."""
    # Arrange
    shorten_wall_limit(monkeypatch)
    code = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(40)'],"
        " start_new_session=True)\n"
        "time.sleep(40)\n"
    )

    # Act
    with anyio.fail_after(PROMPT_SECONDS):
        result = await run_as_slot_user(code)

    # Assert
    assert result.outcome == "timeout"
    assert await wait_until(is_slot_user_idle, DEATH_SECONDS)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "detached",
    [
        SLEEPS,
        REPLACES_ITSELF,
        SIGNALS_ITS_USER.format(name="SIGSTOP"),
        SIGNALS_ITS_USER.format(name="SIGKILL"),
    ],
    ids=[
        "sleeping",
        "forever replacing itself",
        "stopping its user's processes",
        "killing its user's processes",
    ],
)
async def test_a_detached_child_does_not_survive_a_successful_run(
    detached: str,
) -> None:
    """A survivor would watch or alter the next user's run, however it resists."""
    # Arrange
    code = f"DETACHED = {detached!r}\n" + START_DETACHED_CHILD

    # Act
    result = await run_as_slot_user(code)

    # Assert
    assert (result.outcome, result.stdout) == ("ok", "done\n"), result.stderr
    assert await wait_until(is_slot_user_idle, DEATH_SECONDS)


@pytest.mark.anyio
async def test_a_cancelled_run_leaves_no_process_behind() -> None:
    """A client that gives up must not leave its code running on the slot."""
    # Arrange
    code = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(40)'],"
        " start_new_session=True)\n"
        "time.sleep(40)\n"
    )

    # Act
    with anyio.fail_after(PROMPT_SECONDS):
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(run_as_slot_user, code)
            started = await wait_until(
                lambda: count_slot_processes() == 2, PROMPT_SECONDS
            )
            tasks.cancel_scope.cancel()

    # Assert
    assert started
    assert await wait_until(is_slot_user_idle, DEATH_SECONDS)


@pytest.mark.anyio
async def test_a_fork_bomb_is_contained_and_the_slot_keeps_working() -> None:
    """Without a process cap one run could fill the container's process table."""
    # Arrange
    bomb = (
        "import os, time\n"
        "forked = 0\n"
        "try:\n"
        "    while True:\n"
        "        if os.fork() == 0:\n"
        "            os.closerange(0, 3)\n"
        "            time.sleep(40)\n"
        "            os._exit(0)\n"
        "        forked += 1\n"
        "except BlockingIOError:\n"
        "    print(forked)\n"
    )
    first = await run_as_slot_user(bomb)

    # Act
    second = await run_as_slot_user("print('alive')")

    # Assert
    assert first.outcome == "ok", first.stderr
    # Stopped by the slot's cap, far below the container's 256; the kernel's count
    # can sit a process under the cap.
    assert MAX_SLOT_PROCESSES // 2 < int(first.stdout) < MAX_SLOT_PROCESSES
    assert (second.outcome, second.stdout) == ("ok", "alive\n")
