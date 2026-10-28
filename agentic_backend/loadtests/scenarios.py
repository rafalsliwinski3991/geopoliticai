"""What one virtual user does, and what each request it sends is recorded as.

A user owns one thread and repeats a round: a chat turn, a research turn (the
expert), the sidebar list, and the thread's history, which reads the
checkpoint the two turns wrote. Every user starts at its own offset within the
ramp-up, so the arrival rate climbs instead of landing in one instant.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt

from auth import JWT_ALGORITHM, USER_ID_CLAIM
from loadtests.fakes import RESEARCH_KEYWORD

STREAM_PATH = "/api/run_pipeline/stream"
THREADS_PATH = "/api/threads"
CHAT_QUERY = "Hello, what can you do?"
RESEARCH_QUERY = f"Please {RESEARCH_KEYWORD} the state of the ceasefire talks."
USER_ROUND = ("chat", "research", "threads", "history")
TOKEN_LIFETIME = timedelta(hours=1)
DATA_PREFIX = "data: "


@dataclass(frozen=True)
class Sample:
    """One request: whether it succeeded, how long it took, and why it failed.

    `first_token` is the time to the first answer token, for a turn that got one.
    """

    kind: str
    ok: bool
    latency: float
    first_token: float | None = None
    error: str = ""


@dataclass(frozen=True)
class LoadResult:
    """Every sample of one run, and the run's wall time in seconds."""

    samples: list[Sample]
    wall_seconds: float


def mint_token(user_id: int, signing_key: str) -> str:
    """Return an access token with the claims Django's simplejwt mints."""
    return jwt.encode(
        {
            USER_ID_CLAIM: str(user_id),
            "token_type": "access",
            "exp": datetime.now(UTC) + TOKEN_LIFETIME,
            "jti": uuid4().hex,
        },
        signing_key,
        algorithm=JWT_ALGORITHM,
    )


def parse_frame(line: str) -> dict[str, object] | None:
    """Return the JSON frame of an SSE `data:` line, or None for any other line."""
    if not line.startswith(DATA_PREFIX):
        return None
    frame: dict[str, object] = json.loads(line.removeprefix(DATA_PREFIX))
    return frame


async def stream_turn(
    client: httpx.AsyncClient, kind: str, *, thread_id: str, query: str, token: str
) -> Sample:
    """Send one turn and read its stream to the end; only a `result` frame is a success."""
    started = time.perf_counter()
    first_token: float | None = None
    last: dict[str, object] = {}
    try:
        async with client.stream(
            "POST",
            STREAM_PATH,
            json={"query": query, "thread_id": thread_id},
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
            if response.status_code != 200:
                await response.aread()
                return Sample(
                    kind,
                    ok=False,
                    latency=time.perf_counter() - started,
                    error=f"http {response.status_code}",
                )
            async for line in response.aiter_lines():
                frame = parse_frame(line)
                if frame is None:
                    continue
                if frame.get("type") == "token" and first_token is None:
                    first_token = time.perf_counter() - started
                last = frame
    except httpx.HTTPError as exc:
        return Sample(
            kind,
            ok=False,
            latency=time.perf_counter() - started,
            error=type(exc).__name__,
        )
    latency = time.perf_counter() - started
    if last.get("type") == "result":
        return Sample(kind, ok=True, latency=latency, first_token=first_token)
    if last.get("type") == "error":
        error = f"error frame {last.get('status')}"
    else:
        error = "stream ended without a result"
    return Sample(kind, ok=False, latency=latency, first_token=first_token, error=error)


async def send_get(
    client: httpx.AsyncClient, kind: str, *, path: str, token: str
) -> Sample:
    """Send one GET; any status but 200 is a failure."""
    started = time.perf_counter()
    try:
        response = await client.get(path, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        return Sample(
            kind,
            ok=False,
            latency=time.perf_counter() - started,
            error=type(exc).__name__,
        )
    latency = time.perf_counter() - started
    if response.status_code != 200:
        return Sample(
            kind, ok=False, latency=latency, error=f"http {response.status_code}"
        )
    return Sample(kind, ok=True, latency=latency)


async def run_user(
    client: httpx.AsyncClient,
    *,
    user_id: int,
    rounds: int,
    start_after: float,
    signing_key: str,
) -> list[Sample]:
    """Run one virtual user's rounds, in order, after its ramp-up offset."""
    await asyncio.sleep(start_after)
    token = mint_token(user_id, signing_key)
    thread_id = f"load-{user_id}-{uuid4().hex[:12]}"
    samples: list[Sample] = []
    for _ in range(rounds):
        for kind in USER_ROUND:
            if kind in ("chat", "research"):
                query = CHAT_QUERY if kind == "chat" else RESEARCH_QUERY
                sample = await stream_turn(
                    client, kind, thread_id=thread_id, query=query, token=token
                )
            else:
                path = (
                    THREADS_PATH if kind == "threads" else f"{THREADS_PATH}/{thread_id}"
                )
                sample = await send_get(client, kind, path=path, token=token)
            samples.append(sample)
    return samples


async def run_load(
    client: httpx.AsyncClient,
    *,
    users: int,
    rounds: int,
    ramp_up: float,
    signing_key: str,
) -> LoadResult:
    """Run every virtual user concurrently and collect their samples."""
    started = time.perf_counter()
    per_user = await asyncio.gather(
        *(
            run_user(
                client,
                user_id=index + 1,
                rounds=rounds,
                start_after=ramp_up * index / users,
                signing_key=signing_key,
            )
            for index in range(users)
        )
    )
    return LoadResult(
        samples=[sample for samples in per_user for sample in samples],
        wall_seconds=time.perf_counter() - started,
    )
