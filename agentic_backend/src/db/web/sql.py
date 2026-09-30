"""Raw-psycopg access to the Django-owned `chat_threads`, `quota`, `site_quota`, and `users_user` tables.

`agentic_backend/` owns no schema and runs no migrations: Django's `manage.py migrate`
creates every table named here. The coupling is real and accepted;
`tests/integration_tests/test_db_web_schema.py` is what makes it safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

MAX_TITLE_LENGTH = 60
# The thread id Django's `chat_threads.id` column holds, and therefore the cap
# `api.RunPipelineRequest` validates against.
MAX_THREAD_ID_LENGTH = 100

UPSERT_THREAD = """
INSERT INTO chat_threads (id, user_id, title, created_at)
VALUES (%(thread_id)s, %(user_id)s, %(title)s, NOW())
ON CONFLICT (id) DO NOTHING
"""
SELECT_THREAD_OWNER = "SELECT user_id FROM chat_threads WHERE id = %(thread_id)s"
SELECT_THREADS = """
SELECT id, title, created_at
FROM chat_threads
WHERE user_id = %(user_id)s
ORDER BY created_at DESC
"""
SELECT_IS_STAFF = "SELECT is_staff FROM users_user WHERE id = %(user_id)s"
SELECT_QUOTA_USED = """
SELECT used FROM quota WHERE user_id = %(user_id)s AND day = %(day)s
"""
# Conditional and atomic: the WHERE on the conflict target makes the database,
# not the application, the thing that decides whether a turn is affordable. It
# returns no row when the cap is already reached, which is how N concurrent
# requests that all passed the door check still consume only the turns that
# remain. A plain `used = quota.used + 1` lets concurrency buy extras.
# `cost` is how many units this turn spends (1, or DEEP_RESEARCH_TURN_COST); the
# turn is affordable only when all of it fits, so a partial balance buys nothing.
# The cost is validated in Python (`increment_quota`), so a fresh row (the
# INSERT arrow) can never carry a cost the cap rejects. The WHERE on the
# conflict target covers the update path — with the row already there — and is
# how N concurrent requests that all pass the door check still consume only the
# turns that remain; a plain `used = quota.used + cost` would let them buy
# extras.
INCREMENT_QUOTA = """
INSERT INTO quota (user_id, day, used)
VALUES (%(user_id)s, %(day)s, %(cost)s)
ON CONFLICT (user_id, day) DO UPDATE SET used = quota.used + %(cost)s
WHERE quota.used + %(cost)s <= %(limit)s
RETURNING used
"""

# The same conditional upsert against the site-wide counter: `day` is the
# primary key, so one row per UTC day, and no row comes back at the ceiling.
INCREMENT_SITE_QUOTA = """
INSERT INTO site_quota (day, used)
VALUES (%(day)s, %(cost)s)
ON CONFLICT (day) DO UPDATE SET used = site_quota.used + %(cost)s
WHERE site_quota.used + %(cost)s <= %(limit)s
RETURNING used
"""


def title_from(query: str) -> str:
    """Derive a thread title from the first query."""
    cleaned = " ".join(query.split())
    return cleaned[:MAX_TITLE_LENGTH]


@dataclass(frozen=True)
class ThreadRow:
    """One row of the caller's thread list."""

    id: str
    title: str
    created_at: datetime


async def claim_thread(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
    *,
    thread_id: str,
    user_id: int,
    title: str,
) -> bool:
    """Create the thread if it is new; report whether it belongs to this user.

    One round trip creates it and a second reads the owner, because
    `ON CONFLICT DO NOTHING` returns no row when the thread already exists and
    the existing owner is exactly what must be checked. `title` must be a
    string, never None: the column is NOT NULL and Postgres checks that before
    the arbiter index, so a None would raise NotNullViolation even when the
    upsert conflicts.
    """
    async with pool.connection() as conn:
        await conn.execute(
            UPSERT_THREAD,
            {"thread_id": thread_id, "user_id": user_id, "title": title},
        )
        cursor = await conn.execute(SELECT_THREAD_OWNER, {"thread_id": thread_id})
        row = await cursor.fetchone()
    return bool(row) and (row or {}).get("user_id") == user_id


async def owns_thread(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
    *,
    thread_id: str,
    user_id: int,
) -> bool:
    """Report whether this thread exists and belongs to this user."""
    async with pool.connection() as conn:
        cursor = await conn.execute(SELECT_THREAD_OWNER, {"thread_id": thread_id})
        row = await cursor.fetchone()
    return bool(row) and (row or {}).get("user_id") == user_id


async def list_threads(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]], *, user_id: int
) -> list[ThreadRow]:
    """Return the caller's threads, newest first, for the sidebar."""
    async with pool.connection() as conn:
        cursor = await conn.execute(SELECT_THREADS, {"user_id": user_id})
        rows = await cursor.fetchall()
    return [
        ThreadRow(id=row["id"], title=row["title"], created_at=row["created_at"])
        for row in rows
    ]


async def is_staff(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]], *, user_id: int
) -> bool:
    """Re-read `is_staff` from Postgres rather than trusting a token claim."""
    async with pool.connection() as conn:
        cursor = await conn.execute(SELECT_IS_STAFF, {"user_id": user_id})
        row = await cursor.fetchone()
    return bool(row and (row or {}).get("is_staff"))


async def quota_used(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]], *, user_id: int
) -> int:
    """Return the research turns this identity has spent today (0 when none)."""
    async with pool.connection() as conn:
        cursor = await conn.execute(
            SELECT_QUOTA_USED, {"user_id": user_id, "day": _today()}
        )
        row = await cursor.fetchone()
    return int((row or {}).get("used") or 0)


async def increment_quota(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
    *,
    user_id: int,
    limit: int,
    cost: int = 1,
) -> int | None:
    """Spend `cost` research units atomically; None when they do not all fit.

    A non-positive or over-cap `cost` is refused before any SQL runs: a fresh
    day's INSERT puts `cost` into `used` directly, so the database's conflict
    WHERE (which sees only the existing row) cannot rate it — the Python guard
    below decides affordability for that path exactly as the upsert's WHERE
    decides it for every later one.

    The conditional upsert means N concurrent turns cannot buy extras: the
    database decides affordability, and the door check (`quota_used`) is only
    there for the clean pre-stream 429.
    """
    if cost <= 0 or cost > limit:
        return None
    async with pool.connection() as conn:
        cursor = await conn.execute(
            INCREMENT_QUOTA,
            {"user_id": user_id, "day": _today(), "limit": limit, "cost": cost},
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return int(row["used"])


async def increment_site_quota(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]], *, limit: int, cost: int = 1
) -> int | None:
    """Spend `cost` units from the site-wide ceiling; None when they do not all fit."""
    if cost <= 0 or cost > limit:
        return None
    async with pool.connection() as conn:
        cursor = await conn.execute(
            INCREMENT_SITE_QUOTA, {"day": _today(), "limit": limit, "cost": cost}
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return int(row["used"])


def _today() -> date:
    """Return the quota day, in UTC: the quota resets at midnight UTC."""
    return datetime.now(UTC).date()
