"""Raw-psycopg access to the Django-owned `chat_threads`, `quota`, and `users_user` tables.

`agentic_backend/` owns no schema and runs no migrations: Django's `manage.py migrate`
creates every table named here. The coupling is real and accepted;
`tests/integration_tests/test_schema_drift.py` is what makes it safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

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
INCREMENT_QUOTA = """
INSERT INTO quota (user_id, day, used)
VALUES (%(user_id)s, %(day)s, 1)
ON CONFLICT (user_id, day) DO UPDATE SET used = quota.used + 1
WHERE quota.used < %(limit)s
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
) -> int | None:
    """Spend one research turn atomically; None when the cap is already reached.

    The conditional upsert means N concurrent turns cannot buy extras: the
    database decides affordability, and the door check (`quota_used`) is only
    there for the clean pre-stream 429.
    """
    async with pool.connection() as conn:
        cursor = await conn.execute(
            INCREMENT_QUOTA, {"user_id": user_id, "day": _today(), "limit": limit}
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return int(row["used"])


def _today() -> date:
    """Return the quota day, in UTC: the quota resets at midnight UTC."""
    return datetime.now(timezone.utc).date()
