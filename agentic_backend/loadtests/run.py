"""Load-test the API against faked providers, and fail when a limit is crossed.

From `agentic_backend/`: `uv run python -m loadtests.run --users 50 --rounds 3`.
Without `--base-url` it starts `loadtests.server` in a child process on a free
port, with a fresh random signing key, and stops it afterwards; with one it
targets a server you started, signing with your `JWT_SIGNING_KEY`. Exits 1
when any request kind breaks `--max-error-rate` or `--max-p95`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import asdict

import httpx

from loadtests.scenarios import LoadResult, run_load
from loadtests.server import DEFAULT_HOST, PROFILES
from loadtests.stats import find_breaches, format_report, summarize

STARTUP_TIMEOUT_SECONDS = 60.0
STARTUP_POLL_SECONDS = 0.2
REQUEST_TIMEOUT_SECONDS = 120.0
HEALTH_PATH = "/api/health"


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
def spawned_server(profile: str, signing_key: str) -> Iterator[str]:
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
        server.wait(timeout=10)


async def run_load_over_http(
    base_url: str, *, users: int, rounds: int, ramp_up: float, signing_key: str
) -> LoadResult:
    """Run the virtual users against `base_url` over one shared connection pool."""
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        limits=httpx.Limits(max_connections=users, max_keepalive_connections=users),
    ) as client:
        return await run_load(
            client,
            users=users,
            rounds=rounds,
            ramp_up=ramp_up,
            signing_key=signing_key,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the runner's flags."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=50, help="concurrent users")
    parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help="rounds per user; each sends three rate-limited requests, and the "
        "API allows 20 per user per minute",
    )
    parser.add_argument(
        "--ramp-up", type=float, default=5.0, help="seconds over which users start"
    )
    parser.add_argument("--profile", choices=sorted(PROFILES), default="realistic")
    parser.add_argument(
        "--base-url", help="target a running loadtests.server instead of starting one"
    )
    parser.add_argument(
        "--max-error-rate",
        type=float,
        default=0.0,
        help="largest share of failed requests allowed per kind",
    )
    parser.add_argument(
        "--max-p95", type=float, help="largest p95 latency in seconds allowed per kind"
    )
    parser.add_argument("--json-out", help="also write the summaries to this file")
    args = parser.parse_args(argv)
    if args.users < 1 or args.rounds < 1 or args.ramp_up < 0:
        parser.error("--users and --rounds must be positive and --ramp-up not negative")
    return args


def main(argv: list[str] | None = None) -> int:
    """Run one load test, print its report, and return the exit status."""
    args = parse_args(argv)
    if args.base_url:
        signing_key = os.environ.get("JWT_SIGNING_KEY", "")
        if not signing_key:
            sys.exit(
                "--base-url needs the server's JWT_SIGNING_KEY in the environment."
            )
        server: AbstractContextManager[str] = nullcontext(args.base_url)
    else:
        signing_key = secrets.token_urlsafe(48)
        server = spawned_server(args.profile, signing_key)
    with server as base_url:
        result = asyncio.run(
            run_load_over_http(
                base_url,
                users=args.users,
                rounds=args.rounds,
                ramp_up=args.ramp_up,
                signing_key=signing_key,
            )
        )
    summaries = summarize(result.samples)
    print(format_report(result, summaries))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as out:
            json.dump(
                {
                    "users": args.users,
                    "rounds": args.rounds,
                    "profile": args.profile,
                    "wall_seconds": result.wall_seconds,
                    "kinds": [asdict(summary) for summary in summaries],
                },
                out,
                indent=2,
            )
    breaches = find_breaches(
        summaries, max_error_rate=args.max_error_rate, max_p95=args.max_p95
    )
    for breach in breaches:
        print(f"FAIL {breach}")
    return 1 if breaches else 0


if __name__ == "__main__":
    sys.exit(main())
