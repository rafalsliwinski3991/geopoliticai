"""Raw-psycopg access to the Django-owned `chat_threads` and `quota` tables.

`agentic_backend/` owns no schema and runs no migrations: Django's `manage.py migrate`
creates every table named here (Q3c). The coupling is real and accepted (Q10,
brainstorm §4.1); `tests/integration_tests/test_schema_drift.py` is what makes
it safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool

MAX_TITLE_LENGTH = 60

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

# Every statement above, with a parameter set that is valid but matches nothing.
# `test_schema_drift` executes each one so a renamed column fails in CI.
DRIFT_PROBES: tuple[tuple[str, dict[str, Any]], ...] = (
    (SELECT_THREAD_OWNER, {"thread_id": "drift-probe"}),
    (SELECT_THREADS, {"user_id": 0}),
    (SELECT_IS_STAFF, {"user_id": 0}),
)


def title_from(query: str) -> str:
    """Derive a thread title from the first query (Q15)."""
    cleaned = " ".join(query.split())
    return cleaned[:MAX_TITLE_LENGTH]


@dataclass(frozen=True)
class ThreadRow:
    """One row of the caller's thread list."""

    id: str
    title: str
    created_at: str


async def claim_thread(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
    *,
    thread_id: str,
    user_id: int,
    title: str | None,
) -> bool:
    """Create the thread if it is new; report whether it belongs to this user.

    One round trip creates it and a second reads the owner, because
    `ON CONFLICT DO NOTHING` returns no row when the thread already exists and
    the existing owner is exactly what must be checked.
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
    return bool(row and row["is_staff"])
