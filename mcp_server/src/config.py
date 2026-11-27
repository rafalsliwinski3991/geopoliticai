"""Limits and settings for the code sandbox. Edited here, never read from `.env`."""

from __future__ import annotations

import os
from dataclasses import dataclass

# The child's whole environment. One BLAS thread: under the 256 MB address-space
# cap OpenBLAS's default thread pool fails to allocate (measured 2026-11-27).
CHILD_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "HOME": "/nonexistent",
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}
# One OS user per run slot, set only in the image (Dockerfile `ENV`), so two
# concurrent runs from different users cannot signal or inspect each other.
# Unset on a developer's host: unit tests run children as the current user. In
# the image a server that cannot switch users fails every run (PermissionError
# -> server fault -> SandboxUnavailableError), never runs code as itself.
SLOT_USERS: tuple[str | None, ...] = (
    tuple(os.environ["SANDBOX_SLOT_USERS"].split(","))
    if os.environ.get("SANDBOX_SLOT_USERS")
    else (None,)
)
# The sweep's real and saved uid (`runner.SWEEP_PROGRAM`). It must belong to no
# user and no other process, so that no run can signal the sweep.
SWEEP_UID = 10009
# Exact Host headers the MCP SDK accepts (its default is localhost only, else 421).
ALLOWED_HOSTS = (
    "mcp-server",
    "mcp-server:*",
    "localhost",
    "localhost:*",
    "127.0.0.1",
    "127.0.0.1:*",
)


@dataclass(frozen=True)
class RunLimits:
    """Caps on one run and on the server (brainstorm Q15).

    A measured run (numpy + pandas, 30-row table) takes 0.65 s and peaks at 75 MB,
    so 256 MB is three times a typical run. One slot x 256 MB plus the server
    (~60 MB) stays under Compose's 384 MB `mem_limit`. `max_processes` is
    RLIMIT_NPROC, counted per uid, so it is per slot, and applied only when the run
    switches user. `reap_seconds` bounds the cleanup after a run: the sweep of the
    slot user's processes, then the wait for the child.
    """

    wall_seconds: float = 10.0
    cpu_seconds: int = 10
    memory_bytes: int = 256 * 1024 * 1024
    max_processes: int = 64
    code_bytes: int = 20_000
    output_bytes: int = 10_000
    queue_seconds: float = 15.0
    reap_seconds: float = 5.0


LIMITS = RunLimits()
