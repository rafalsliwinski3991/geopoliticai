"""The in-process per-client rate limit."""

from __future__ import annotations

import logging
import time
from collections import deque
from threading import Lock

from fastapi import HTTPException, Request

from api.auth import Identity

logger = logging.getLogger(__name__)

RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW_SECONDS = 60
MAX_TRACKED_CLIENTS = 10_000

_rate_limit_store: dict[str, deque[float]] = {}
_rate_limit_lock = Lock()


def _resolve_client_id(request: Request, identity: Identity | None = None) -> str:
    """Resolve a rate-limit key: the authenticated user, else the client address.

    nginx appends the connecting peer as the last `X-Forwarded-For` entry, so
    the right-most value is the address this request actually came from. Taking
    the first entry instead would let a caller spoof the id and rotate it to
    dodge the rate limit.

    Keyed on the authenticated user id when there is one (§7, Q17): a signed-in
    caller must not be able to rotate the forwarded header to dodge their
    bucket. The unauthenticated fallback keeps the spoofing note above: a
    header-based id is spoofable, and the daily quota in Postgres is the real
    bound on an authenticated caller. ponytail: the window is in-process, so
    with more than one uvicorn worker the per-minute limit multiplies by the
    worker count; the daily quota backstops it.
    """
    if identity is not None:
        return f"user:{identity.user_id}"
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[-1].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _flush_stale_clients(now: float) -> None:
    """Drop clients whose request windows have fully drained.

    Keeps the in-process rate-limit store from growing without bound as new
    client ids arrive.
    """
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    for client_id, timestamps in list(_rate_limit_store.items()):
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        if not timestamps:
            del _rate_limit_store[client_id]


def enforce_rate_limit(request: Request, identity: Identity | None = None) -> None:
    """Apply the in-process per-client rate limit."""
    now = time.monotonic()
    client_id = _resolve_client_id(request, identity)
    with _rate_limit_lock:
        timestamps = _rate_limit_store.get(client_id)
        if timestamps is None:
            if len(_rate_limit_store) >= MAX_TRACKED_CLIENTS:
                _flush_stale_clients(now)
                if len(_rate_limit_store) >= MAX_TRACKED_CLIENTS:
                    # Hard bound: evict the least recently seen client.
                    del _rate_limit_store[next(iter(_rate_limit_store))]
            timestamps = deque()
        cutoff = now - RATE_LIMIT_WINDOW_SECONDS
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        if len(timestamps) >= RATE_LIMIT_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: max {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW_SECONDS} seconds.",
            )
        timestamps.append(now)
        _rate_limit_store[client_id] = timestamps
