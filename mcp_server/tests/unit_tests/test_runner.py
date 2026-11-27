import asyncio
import os
import signal
import subprocess
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import anyio
import pytest

import runner
from config import LIMITS
from runner import classify, run_code

SHORT_WALL_SECONDS = 0.5
SHORT_REAP_SECONDS = 0.5
OUTPUT_CAP_BYTES = 10_000
PAST_MEMORY_CAP_BYTES = 512 * 1024 * 1024
# How long a process may take to die after SIGKILL before a test calls it alive.
DEATH_SECONDS = 2.0
# Starts a long sleeper in the run's own process group, holding none of its pipes.
START_LINGERING_CHILD = """
import subprocess, sys
child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(30)"],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
"""
CHILD_ENV_NAMES = [
    "HOME",
    "LANG",
    "MKL_NUM_THREADS",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "PATH",
]


class RecordingSweep:
    """Stands in for `kill_user_processes` and records whom it was asked to kill."""

    def __init__(self) -> None:
        self.users: list[str | None] = []

    def __call__(self, user: str | None) -> None:
        self.users.append(user)


def shorten_limits(monkeypatch: pytest.MonkeyPatch, **changes: float) -> None:
    monkeypatch.setattr(runner, "LIMITS", replace(LIMITS, **changes))


def is_running(pid: int) -> bool:
    """Whether `pid` can still execute; a zombie cannot."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return False
    return stat.rpartition(")")[2].split()[0] not in ("Z", "X")


async def wait_until(condition: Callable[[], bool]) -> bool:
    with anyio.move_on_after(DEATH_SECONDS):
        while not condition():
            await anyio.sleep(0.02)
        return True
    return False


@pytest.mark.anyio
async def test_a_run_returns_what_the_code_printed() -> None:
    """The model only ever learns a result from what its code prints."""
    # Arrange
    code = "print(6 * 7)"

    # Act
    result = await run_code(code, run_as=None)

    # Assert
    assert (result.outcome, result.stdout, result.exit_code) == ("ok", "42\n", 0)


@pytest.mark.anyio
async def test_a_failing_program_is_reported_as_an_error_with_its_traceback() -> None:
    """The model can only fix its code if it sees why it failed."""
    # Arrange
    code = "raise ValueError('no such year')"

    # Act
    result = await run_code(code, run_as=None)

    # Assert
    assert (result.outcome, result.exit_code) == ("error", 1)
    assert "Traceback" in result.stderr
    assert "ValueError: no such year" in result.stderr


@pytest.mark.anyio
async def test_a_run_past_the_wall_limit_is_killed_and_reported_as_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An endless loop must not hold the only run slot."""
    # Arrange
    shorten_limits(monkeypatch, wall_seconds=SHORT_WALL_SECONDS)

    # Act
    result = await run_code("while True: pass", run_as=None)

    # Assert
    assert (result.outcome, result.exit_code) == ("timeout", None)


@pytest.mark.anyio
async def test_a_sleeping_run_is_stopped_by_the_wall_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sleeper spends no CPU time, so only the wall limit can stop it."""
    # Arrange
    shorten_limits(monkeypatch, wall_seconds=SHORT_WALL_SECONDS)

    # Act
    with anyio.fail_after(DEATH_SECONDS + SHORT_WALL_SECONDS):
        result = await run_code("import time; time.sleep(60)", run_as=None)

    # Assert
    assert result.outcome == "timeout"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("printed_bytes", "cut"),
    [(OUTPUT_CAP_BYTES, False), (OUTPUT_CAP_BYTES + 1, True)],
    ids=["at the cap", "one past the cap"],
)
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_output_is_cut_at_the_cap_and_flagged(
    stream: str, printed_bytes: int, cut: bool
) -> None:
    """Unbounded output would flood the model's context and the server's memory."""
    # Arrange
    code = f"import sys; sys.{stream}.write('x' * {printed_bytes})"

    # Act
    result = await run_code(code, run_as=None)

    # Assert
    assert getattr(result, stream) == "x" * OUTPUT_CAP_BYTES
    assert result.truncated is cut


@pytest.mark.anyio
async def test_allocating_past_the_memory_cap_is_reported_as_out_of_memory() -> None:
    """One greedy run must not exhaust the container, and the model must know why."""
    # Arrange
    code = f"data = bytearray({PAST_MEMORY_CAP_BYTES})"

    # Act
    result = await run_code(code, run_as=None)

    # Assert
    assert result.outcome == "oom"


@pytest.mark.anyio
async def test_numpy_and_pandas_work_under_the_memory_cap() -> None:
    """OpenBLAS's default thread pool cannot allocate under the address-space cap."""
    # Arrange
    code = (
        "import numpy, pandas\n"
        "matrix = numpy.ones((500, 500))\n"
        "frame = pandas.DataFrame({'gdp': [1.0, 2.0, 3.0]})\n"
        "print((matrix @ matrix).sum(), frame['gdp'].mean())\n"
    )

    # Act
    result = await run_code(code, run_as=None)

    # Assert
    assert (result.outcome, result.stdout) == ("ok", "125000000.0 2.0\n")


@pytest.mark.anyio
async def test_the_child_sees_none_of_the_servers_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model-written code is untrusted and must not read the server's variables."""
    # Arrange
    monkeypatch.setenv("SECRET_X", "do-not-leak")

    # Act
    result = await run_code("import os; print(sorted(os.environ))", run_as=None)

    # Assert
    assert result.stdout == f"{CHILD_ENV_NAMES}\n"


@pytest.mark.anyio
async def test_a_second_run_cannot_see_the_first_runs_variables() -> None:
    """Runs belong to different users, so nothing may carry over between them."""
    # Arrange
    await run_code("private_note = 'first user'", run_as=None)

    # Act
    result = await run_code("print(private_note)", run_as=None)

    # Assert
    assert result.outcome == "error"
    assert "NameError" in result.stderr


@pytest.mark.parametrize(
    "exit_code",
    [-signal.SIGXCPU, -signal.SIGKILL],
    ids=["soft CPU limit", "hard CPU limit"],
)
def test_a_cpu_limit_kill_counts_as_a_timeout(exit_code: int) -> None:
    """The kernel ends a run that spent its CPU time with one of these signals."""
    # Arrange
    stderr = ""

    # Act
    outcome = classify(exit_code, stderr, timed_out=False)

    # Assert
    assert outcome == "timeout"


@pytest.mark.parametrize(
    "exit_code",
    [1, 2, -signal.SIGSEGV, -signal.SIGTERM],
    ids=["exception", "usage error", "crash", "terminated"],
)
def test_any_other_failing_exit_counts_as_an_error(exit_code: int) -> None:
    """Calling an ordinary crash a timeout would send the model after the wrong fix."""
    # Arrange
    stderr = ""

    # Act
    outcome = classify(exit_code, stderr, timed_out=False)

    # Assert
    assert outcome == "error"


@pytest.mark.anyio
async def test_a_process_left_in_the_runs_group_dies_with_a_successful_run() -> None:
    """A leftover process would live on into the next user's run."""
    # Arrange
    code = START_LINGERING_CHILD + "print(child.pid)"

    # Act
    result = await run_code(code, run_as=None)

    # Assert
    child_pid = int(result.stdout)
    assert await wait_until(lambda: not is_running(child_pid))


@pytest.mark.anyio
async def test_a_cancelled_run_leaves_no_process_in_its_group(tmp_path: Path) -> None:
    """The MCP SDK cancels through anyio scopes, which also cancel awaits in `finally`."""
    # Arrange
    pid_file = tmp_path / "child.pid"
    code = START_LINGERING_CHILD + (
        "import pathlib, time\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(f'{{child.pid}}\\n')\n"
        "time.sleep(30)\n"
    )

    def has_started() -> bool:
        return pid_file.exists() and pid_file.read_text().endswith("\n")

    # Act
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(lambda: run_code(code, run_as=None))
        started = await wait_until(has_started)
        tasks.cancel_scope.cancel()

    # Assert
    assert started
    child_pid = int(pid_file.read_text())
    assert await wait_until(lambda: not is_running(child_pid))


@pytest.mark.anyio
async def test_a_run_as_the_current_user_never_sweeps_that_users_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sweeping without a slot user would kill the developer's own processes."""
    # Arrange
    sweep = RecordingSweep()
    monkeypatch.setattr(runner, "kill_user_processes", sweep)

    # Act
    await run_code("print('done')", run_as=None)

    # Assert
    assert sweep.users == []


@pytest.mark.anyio
async def test_a_failed_sweep_is_a_server_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A result returned over leftover processes would let the next run meet them."""
    # Arrange
    start_as_current_user = runner.start_child

    async def start_child(run_as: str | None) -> asyncio.subprocess.Process:
        return await start_as_current_user(None)

    def fail_to_sweep(user: str) -> None:
        raise subprocess.CalledProcessError(1, "sweep")

    monkeypatch.setattr(runner, "start_child", start_child)
    monkeypatch.setattr(runner, "kill_user_processes", fail_to_sweep)

    # Act + Assert
    with pytest.raises(subprocess.CalledProcessError):
        await run_code("print('done')", run_as="sandbox0")


@pytest.mark.anyio
async def test_a_child_that_cannot_be_reaped_in_time_is_a_server_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Waiting forever for a child that survived the kill would hold the only slot."""
    # Arrange
    shorten_limits(
        monkeypatch,
        wall_seconds=SHORT_WALL_SECONDS,
        reap_seconds=SHORT_REAP_SECONDS,
    )
    survivors: list[int] = []
    monkeypatch.setattr(runner, "kill_group", survivors.append)

    # Act + Assert
    with pytest.raises(TimeoutError):
        await run_code("import time; time.sleep(30)", run_as=None)

    os.killpg(survivors[0], signal.SIGKILL)
    assert await wait_until(lambda: not is_running(survivors[0]))
