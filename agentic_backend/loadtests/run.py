"""Start the faked API, load-test it with Locust, and exit with Locust's status.

From `agentic_backend/`: `uv run python -m loadtests.run`, then any of Locust's
own flags, which win over the defaults below:
`uv run python -m loadtests.run --profile instant --users 100 --spawn-rate 20 --csv results/run`.
`--max-p95 SECONDS` fails the run when any row's p95 is over it; any failed
request fails it already. The server gets a fresh random signing key, on a
free port, and stops afterwards.
"""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from loadtests.server import DEFAULT_HOST, PROFILES

STARTUP_TIMEOUT_SECONDS = 60.0
STARTUP_POLL_SECONDS = 0.2
SHUTDOWN_TIMEOUT_SECONDS = 10.0
HEALTH_PATH = "/api/health"
LOCUSTFILE = Path(__file__).with_name("locustfile.py")
# 50 users started over 5 s, for a minute; a round in flight at the end may
# finish rather than be cut off.
DEFAULT_LOCUST_ARGS = (
    "--users",
    "50",
    "--spawn-rate",
    "10",
    "--run-time",
    "60s",
    "--stop-timeout",
    "60",
    "--only-summary",
)


def find_free_port() -> int:
    """Return a TCP port nothing on this host listens on right now."""
    with socket.socket() as probe:
        probe.bind((DEFAULT_HOST, 0))
        port: int = probe.getsockname()[1]
        return port


def wait_until_healthy(base_url: str, server: subprocess.Popen[bytes]) -> None:
    """Poll the health route until it answers; raise if the server exits or stalls."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"the load-test server exited with {server.returncode}")
        try:
            if httpx.get(f"{base_url}{HEALTH_PATH}").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(STARTUP_POLL_SECONDS)
    raise RuntimeError("the load-test server did not answer within the startup timeout")


@contextmanager
def spawn_server(profile: str, signing_key: str) -> Iterator[str]:
    """Run `loadtests.server` in a child process; yield its base URL."""
    port = find_free_port()
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "loadtests.server",
            "--host",
            DEFAULT_HOST,
            "--port",
            str(port),
            "--profile",
            profile,
        ],
        env={**os.environ, "JWT_SIGNING_KEY": signing_key},
    )
    try:
        base_url = f"http://{DEFAULT_HOST}:{port}"
        wait_until_healthy(base_url, server)
        yield base_url
    finally:
        server.terminate()
        try:
            server.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            # A server stuck in shutdown must not outlive the run.
            server.kill()
            server.wait()


def main(argv: list[str] | None = None) -> int:
    """Run Locust headless against a fresh server and return its exit status."""
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="realistic")
    args, locust_args = parser.parse_known_args(argv)
    signing_key = secrets.token_urlsafe(48)
    with spawn_server(args.profile, signing_key) as base_url:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "locust",
                "-f",
                str(LOCUSTFILE),
                "--headless",
                "--host",
                base_url,
                *DEFAULT_LOCUST_ARGS,
                *locust_args,
            ],
            env={**os.environ, "JWT_SIGNING_KEY": signing_key},
            check=False,
        ).returncode


if __name__ == "__main__":
    sys.exit(main())
