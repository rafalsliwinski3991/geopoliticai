"""Locust users for the API that `loadtests.server` serves with faked providers.

`python -m loadtests.run` starts that server and runs this file against it. To
target a server you started, sign with its key:
`JWT_SIGNING_KEY=... locust -f loadtests/locustfile.py --host http://127.0.0.1:8765`.

A user owns one thread and repeats a round: a chat turn, a research turn (the
expert), the sidebar list, and the thread's history, which reads the
checkpoint the two turns wrote. Each request is timed here and handed to
Locust's statistics: a streamed turn to its last frame, with its time to the
first answer token as a row of its own.
"""

from __future__ import annotations

import logging
import os
import time
from itertools import count
from typing import Any
from uuid import uuid4

import requests
from locust import User, constant_pacing, events, task
from locust.env import Environment

from loadtests.turns import (
    CHAT_QUERY,
    FIRST_TOKEN,
    RESEARCH_QUERY,
    STREAM_PATH,
    THREADS_PATH,
    find_turn_error,
    mint_token,
    parse_frame,
)

# A round sends three requests the per-user rate limit counts (20 a minute);
# starting one at most every 10 s keeps a user at 18.
ROUND_PACING_SECONDS = 10
REQUEST_TIMEOUT_SECONDS = 120.0
_user_ids = count(1)


class TurnFailed(Exception):
    """A request that did not end well, named by why."""


# Locust's event hooks are untyped.
@events.init_command_line_parser.add_listener  # type: ignore[untyped-decorator]
def add_max_p95_flag(parser: Any) -> None:
    """Add `--max-p95`, the slowest p95 in seconds any row may have."""
    parser.add_argument(
        "--max-p95", type=float, help="fail when any row's p95 is over this, in s"
    )


@events.quitting.add_listener  # type: ignore[untyped-decorator]
def fail_on_slow_p95(environment: Environment, **kwargs: Any) -> None:
    """Exit 1 when a row breaks `--max-p95`; Locust already exits 1 on a failure."""
    limit = getattr(environment.parsed_options, "max_p95", None)
    if limit is None:
        return
    for entry in environment.stats.entries.values():
        p95 = entry.get_response_time_percentile(0.95) / 1000
        if p95 > limit:
            logging.error(
                "%s %s: p95 %.3fs over %.3fs", entry.method, entry.name, p95, limit
            )
            environment.process_exit_code = 1


class ChatUser(User):
    """One person in the chat app, with a thread of their own."""

    wait_time = constant_pacing(ROUND_PACING_SECONDS)

    def on_start(self) -> None:
        """Sign in as a user no other virtual user shares."""
        user_id = next(_user_ids)
        token = mint_token(user_id, os.environ["JWT_SIGNING_KEY"])
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.thread_id = f"load-{user_id}-{uuid4().hex[:12]}"

    @task
    def run_round(self) -> None:
        """Send the four requests of one round, in order."""
        self.send_turn("chat", CHAT_QUERY)
        self.send_turn("research", RESEARCH_QUERY)
        self.send_get("threads", THREADS_PATH)
        self.send_get("history", f"{THREADS_PATH}/{self.thread_id}")

    def send_turn(self, kind: str, query: str) -> None:
        """Stream one turn to its end; record it, and its time to the first token."""
        started = time.perf_counter()
        first_token: float | None = None
        length = 0
        try:
            with self.session.post(
                f"{self.host}{STREAM_PATH}",
                json={"query": query, "thread_id": self.thread_id},
                stream=True,
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as response:
                if response.status_code != 200:
                    error: str | None = f"http {response.status_code}"
                else:
                    last: dict[str, object] = {}
                    for line in response.iter_lines():
                        length += len(line)
                        frame = parse_frame(line.decode())
                        if frame is None:
                            continue
                        if frame.get("type") == "token" and first_token is None:
                            first_token = time.perf_counter() - started
                        last = frame
                    error = find_turn_error(last)
        except requests.RequestException as exc:
            error = type(exc).__name__
        self.record("POST", kind, time.perf_counter() - started, length, error)
        if first_token is not None:
            self.record(FIRST_TOKEN, kind, first_token, 0, None)

    def send_get(self, kind: str, path: str) -> None:
        """Send one GET and record it; any status but 200 is a failure."""
        started = time.perf_counter()
        length = 0
        try:
            response = self.session.get(
                f"{self.host}{path}", timeout=REQUEST_TIMEOUT_SECONDS
            )
            length = len(response.content)
            error = (
                None if response.status_code == 200 else f"http {response.status_code}"
            )
        except requests.RequestException as exc:
            error = type(exc).__name__
        self.record("GET", kind, time.perf_counter() - started, length, error)

    def record(
        self,
        request_type: str,
        name: str,
        seconds: float,
        length: int,
        error: str | None,
    ) -> None:
        """Hand one timing to Locust's statistics."""
        self.environment.events.request.fire(
            request_type=request_type,
            name=name,
            response_time=seconds * 1000,
            response_length=length,
            exception=None if error is None else TurnFailed(error),
            context={},
        )
