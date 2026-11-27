"""Run one piece of model-written Python in a fresh, limited child process.

Every run is treated as hostile (brainstorm Q10): a fresh interpreter in `-I`
isolated mode, a minimal environment, `/` as its working directory (read-only:
it can write nowhere), rlimits, and a wall timeout. Processes are all a run can
leave behind, so every run ends with its process group and, for a slot user, all
of that user's processes killed.
"""

from __future__ import annotations

import asyncio
import functools
import os
import pwd
import resource
import signal
import subprocess
import sys
import time
from typing import Literal

from pydantic import BaseModel

from config import CHILD_ENV, LIMITS, SWEEP_UID

RunOutcome = Literal["ok", "error", "timeout", "oom", "refused"]
READ_CHUNK_BYTES = 65_536
# Run by root. It takes the slot user as its effective uid only, so `kill(-1)`
# reaches that user's processes and nothing else, while none of them can stop or
# kill it: that takes its real or saved uid, which stay `SWEEP_UID`. `kill(-1)`
# is one kernel call, so a process that keeps forking cannot slip past it.
SWEEP_PROGRAM = """
import os, signal, sys
sweep_uid, uid, gid = map(int, sys.argv[1:])
os.setgroups([])
os.setgid(gid)
os.setresuid(sweep_uid, uid, sweep_uid)
try:
    os.kill(-1, signal.SIGKILL)
except ProcessLookupError:
    pass
"""


class RunResult(BaseModel):
    """What one run produced; the MCP tool's structured output."""

    outcome: RunOutcome
    stdout: str
    stderr: str
    exit_code: int | None
    truncated: bool
    duration_ms: int


async def run_code(code: str, *, run_as: str | None) -> RunResult:
    """Run `code` with `python -I -` as `run_as` (None: the current user) and report it."""
    started = time.monotonic()
    process = await start_child(run_as)
    timed_out = False
    stdout, out_cut, stderr, err_cut = b"", False, b"", False
    try:
        async with asyncio.timeout(LIMITS.wall_seconds):
            (stdout, out_cut), (stderr, err_cut), _ = await asyncio.gather(
                read_capped(process.stdout),
                read_capped(process.stderr),
                feed_stdin(process, code),
            )
            await process.wait()
    except TimeoutError:
        timed_out = True
    finally:
        # Nothing here may await: the MCP SDK cancels through anyio scopes, which
        # cancel an `await` in `finally` again.
        kill_group(process.pid)
        if run_as is not None:
            kill_user_processes(run_as)
    # A child that survived the kill is a server fault, not a reason to hold the slot.
    async with asyncio.timeout(LIMITS.reap_seconds):
        exit_code = await process.wait()
    stderr_text = stderr.decode(errors="replace")
    return RunResult(
        outcome=classify(exit_code, stderr_text, timed_out),
        stdout=stdout.decode(errors="replace"),
        stderr=stderr_text,
        exit_code=None if timed_out else exit_code,
        truncated=out_cut or err_cut,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


async def start_child(run_as: str | None) -> asyncio.subprocess.Process:
    """Start an isolated interpreter that reads its program from stdin.

    `user=` is passed only for a slot user: switching needs privileges that a
    developer's host does not give.
    """
    limits = functools.partial(limit_child, cap_processes=run_as is not None)
    if run_as is None:
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="/",
            env=CHILD_ENV,
            start_new_session=True,
            preexec_fn=limits,
        )
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd="/",
        env=CHILD_ENV,
        start_new_session=True,
        preexec_fn=limits,
        user=run_as,
        group=run_as,
        extra_groups=[],
    )


def limit_child(*, cap_processes: bool) -> None:
    """Apply the per-run rlimits in the child, before `exec`.

    The CPU hard limit sits one second above the soft one, so the kernel sends
    SIGXCPU (classified as a timeout) before SIGKILL. RLIMIT_NPROC counts every
    process of the uid, so it is applied only to a slot user: on a developer's
    host it would count the developer's own processes.
    """
    resource.setrlimit(resource.RLIMIT_AS, (LIMITS.memory_bytes, LIMITS.memory_bytes))
    resource.setrlimit(
        resource.RLIMIT_CPU, (LIMITS.cpu_seconds, LIMITS.cpu_seconds + 1)
    )
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if cap_processes:
        resource.setrlimit(
            resource.RLIMIT_NPROC, (LIMITS.max_processes, LIMITS.max_processes)
        )


async def feed_stdin(process: asyncio.subprocess.Process, code: str) -> None:
    """Write the code to the child's stdin and close it."""
    assert process.stdin is not None
    process.stdin.write(code.encode())
    try:
        await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass  # The child exited before reading everything; its exit code says why.
    process.stdin.close()


async def read_capped(stream: asyncio.StreamReader | None) -> tuple[bytes, bool]:
    """Keep the first `LIMITS.output_bytes` of `stream`, drain the rest, report a cut."""
    assert stream is not None
    kept = bytearray()
    truncated = False
    while chunk := await stream.read(READ_CHUNK_BYTES):
        room = LIMITS.output_bytes - len(kept)
        if room > 0:
            kept += chunk[:room]
        if len(chunk) > max(room, 0):
            truncated = True
    return bytes(kept), truncated


def kill_group(pid: int) -> None:
    """SIGKILL the run's whole process group; needs CAP_KILL across uids."""
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def kill_user_processes(user: str) -> None:
    """SIGKILL every process of `user`, also one that left its run's process group.

    Synchronous, so a cancelled run cannot skip it and its slot is not returned
    before it ends; it blocks the event loop for one interpreter start.
    """
    account = pwd.getpwnam(user)
    ids = [str(SWEEP_UID), str(account.pw_uid), str(account.pw_gid)]
    subprocess.run(
        [sys.executable, "-I", "-S", "-c", SWEEP_PROGRAM, *ids],
        cwd="/",
        env=CHILD_ENV,
        check=True,
        timeout=LIMITS.reap_seconds,
    )


def classify(exit_code: int, stderr: str, timed_out: bool) -> RunOutcome:
    """Name the outcome; a CPU-limit kill (SIGXCPU or SIGKILL at the hard limit) is a timeout."""
    if timed_out or exit_code in (-signal.SIGXCPU, -signal.SIGKILL):
        return "timeout"
    if exit_code == 0:
        return "ok"
    if "MemoryError" in stderr or "Memory allocation" in stderr:
        return "oom"
    return "error"
