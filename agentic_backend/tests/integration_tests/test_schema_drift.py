"""The mandatory schema-drift guard (brainstorm flag 4).

Django owns every table these statements touch; `agentic_backend/` addresses
them by name with raw psycopg and runs no migrations of its own. This suite
executes *every* statement in `threads.py` against a database migrated by
Django and set up by the checkpointer, so a renamed or dropped column fails in
CI instead of in production.

Requires a real Postgres: `DATABASE_URL` pointing at a database that
(1) has been migrated by Django (`make migrate`) and (2) has the checkpointer
tables (`AsyncPostgresSaver.setup()` — the tests here run it themselves,
idempotently). The CI `schema-drift` job encodes that order; without
`DATABASE_URL` the suite skips so the ordinary unit run stays hermetic.

The deletion cascade is asserted against rows written by langgraph's own
`PostgresSaver`, using the exact DELETE statements the Django signal
(`web_backend/chat/signals.py`) runs. The signal itself is exercised by the
Django suite; what only an integration database can prove is that those
statements actually match the shape langgraph's writer produces.
"""

import os
import time
from datetime import date
from typing import Any, Generator, cast

import pytest
from langgraph.checkpoint.base import CheckpointMetadata
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection, connect
from psycopg.rows import dict_row

import threads

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="needs a real Postgres (make test-integration)",
)

# The DELETE statements `web_backend/chat/signals.py` runs, mirrored here so a
# rename on either side fails the other side's guard.
CASCADE_SQL = tuple(
    f"DELETE FROM {table} WHERE thread_id = ANY(%s)"
    for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints")
)
# The orphan-check query the brainstorm specifies verbatim (chat.admin).
ORPHAN_THREAD_SQL = """
SELECT DISTINCT thread_id
FROM checkpoints
WHERE thread_id NOT IN (SELECT id FROM chat_threads)
"""


@pytest.fixture(scope="module")
def url() -> str:
    return os.environ["DATABASE_URL"]


@pytest.fixture(scope="module")
def conn(url: str) -> Generator[Connection[dict[str, Any]], None, None]:
    """One autocommit connection per module; tests clean up after themselves."""
    with connect(url, autocommit=True, row_factory=dict_row) as connection:
        yield connection


@pytest.fixture(scope="module")
def checkpointer(url: str) -> Generator[PostgresSaver, None, None]:
    """The checkpointer's tables, created by its own `setup()` if missing."""
    with PostgresSaver.from_conn_string(url) as saver:
        saver.setup()
        yield saver


@pytest.fixture
def user_id(
    conn: Connection[dict[str, Any]],
) -> Generator[int, None, None]:
    """One Django-schema user per test, deleted afterwards.

    The teardown deletes the user's chat_threads rows first: `chat_threads.user_id`
    is the one FK that DOES reach the user table, and the fixture's own threads
    would block the delete.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO users_user (
                password, is_superuser, is_staff, is_active, date_joined, email,
                first_name, last_name
            )
            VALUES (
                'integration-test-not-a-real-hash', FALSE, FALSE, TRUE, NOW(), %s,
                '', ''
            )
            RETURNING id
            """,
            (f"drift-{os.getpid()}-{time.time_ns()}@example.com",),
        )
        created = cast(Any, cursor.fetchone())["id"]
    yield created
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM chat_threads WHERE user_id = %s", (created,))
        cursor.execute("DELETE FROM quota WHERE user_id = %s", (created,))
        cursor.execute("DELETE FROM users_user WHERE id = %s", (created,))


def _empty_checkpoint() -> Any:
    """A minimal well-formed checkpoint; content is irrelevant to the SQL."""
    from datetime import datetime, timezone

    return {
        "v": "1",
        "id": "drift-checkpoint-id",
        "ts": datetime.now(timezone.utc).isoformat(),
        "channel_values": {},
        "channel_versions": {},
        "versions_seen": {},
    }


def test_every_drift_probe_executes(conn: Connection[dict[str, Any]]) -> None:
    """A renamed or dropped column fails here, and only here, before production."""
    # Arrange + Act + Assert: every probe must execute a valid, no-match query.
    for statement, params in threads.DRIFT_PROBES:
        with conn.cursor() as cursor:
            cursor.execute(statement, params)
            cursor.fetchall()


def test_upsert_thread_creates_once_and_the_owner_is_read_back(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    # Arrange
    # Arrange
    with conn.cursor() as cursor:
        # Act
        cursor.execute(
            threads.UPSERT_THREAD,
            {"thread_id": "drift-1", "user_id": user_id, "title": "NATO"},
        )
        cursor.execute(
            threads.UPSERT_THREAD,
            {"thread_id": "drift-1", "user_id": user_id, "title": "NATO again"},
        )
        cursor.execute(threads.SELECT_THREAD_OWNER, {"thread_id": "drift-1"})
        row = cast(Any, cursor.fetchone())
        cursor.execute("SELECT title FROM chat_threads WHERE id = 'drift-1'")
        title = cast(Any, cursor.fetchone())["title"]

    # Assert
    assert row["user_id"] == user_id
    assert title == "NATO"


def test_select_threads_returns_the_serialized_columns(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    # Arrange
    with conn.cursor() as cursor:
        cursor.execute(
            threads.UPSERT_THREAD,
            {"thread_id": "drift-2", "user_id": user_id, "title": "Lithuania"},
        )
        # Act
        cursor.execute(threads.SELECT_THREADS, {"user_id": user_id})
        rows = cursor.fetchall()
    # Assert
    row = cast(Any, next(r for r in rows if r["id"] == "drift-2"))
    assert row["title"] == "Lithuania"
    assert row["created_at"] is not None


def test_increment_quota_upserts_increments_and_caps(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    """The conditional atomic upsert, both ON CONFLICT branches, for real."""
    # Arrange
    day = date.today()
    with conn.cursor() as cursor:
        cursor.execute(
            threads.INCREMENT_QUOTA, {"user_id": user_id, "day": day, "limit": 2}
        )
        first = cast(Any, cursor.fetchone())["used"]
        cursor.execute(
            threads.INCREMENT_QUOTA, {"user_id": user_id, "day": day, "limit": 2}
        )
        second = cast(Any, cursor.fetchone())["used"]
        cursor.execute(
            threads.INCREMENT_QUOTA, {"user_id": user_id, "day": day, "limit": 2}
        )
        capped = cursor.fetchone()

    # Assert
    assert (first, second) == (1, 2)
    # The WHERE on the conflict target decides affordability: no row at the cap.
    assert capped is None


def test_deleting_a_user_cascades_into_the_checkpointer_tables(
    conn: Connection[dict[str, Any]], checkpointer: PostgresSaver, user_id: int
) -> None:
    """Q19: no FK reaches the checkpointer tables; the signal's DELETEs must.

    Mirrors Django's delete order honestly: Django emulates FK cascades in the
    ORM, so the sequence the production delete follows is the signal's
    checkpointer DELETEs (pre_delete), then the ORM's chat_threads/quota
    cascade, then the user row.
    """
    # Arrange
    thread_id = "drift-3"
    with conn.cursor() as cursor:
        cursor.execute(
            threads.UPSERT_THREAD,
            {"thread_id": thread_id, "user_id": user_id, "title": ""},
        )
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = _empty_checkpoint()
    saved_config = checkpointer.put(
        cast(Any, config), checkpoint, CheckpointMetadata(), {}
    )
    checkpointer.put_writes(saved_config, [("channel", "value")], "task-1")

    # Act
    with conn.cursor() as cursor:
        # The signal fires on pre_delete, inside the user-delete transaction.
        for statement in CASCADE_SQL:
            cursor.execute(statement, ([thread_id],))
        cursor.execute("DELETE FROM chat_threads WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM quota WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM users_user WHERE id = %s", (user_id,))

    # Assert
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) AS n FROM chat_threads WHERE id = %s", (thread_id,)
        )
        assert cast(Any, cursor.fetchone())["n"] == 0
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            cursor.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE thread_id = %s", (thread_id,)
            )
            assert cast(Any, cursor.fetchone())["n"] == 0, table


def test_the_site_wide_sentinel_can_be_incremented(
    conn: Connection[dict[str, Any]],
) -> None:
    """The reserved sentinel row makes user_id 0 a valid quota spender.

    A missing sentinel row would turn every research turn into a mid-stream
    500: the per-user increment succeeds first, then the site-wide insert hits
    the `quota.user_id` foreign key.
    """
    with conn.cursor() as cursor:
        cursor.execute(
            threads.INCREMENT_QUOTA,
            {"user_id": 0, "day": date.today(), "limit": 10**9},
        )
        spent = cast(Any, cursor.fetchone())
    assert spent is not None and spent["used"] >= 1
    with conn.cursor() as cursor:
        cursor.execute(
            "DELETE FROM quota WHERE user_id = 0 AND used IS NOT NULL AND used > 0 AND day = %s",
            (date.today(),),
        )
        cursor.execute(
            "SELECT COUNT(*) AS n FROM quota WHERE user_id = 0 AND day = %s",
            (date.today(),),
        )
        assert cursor.fetchone() is not None


def test_orphan_query_reports_a_checkpointed_id_and_purges_cleanly(
    conn: Connection[dict[str, Any]], checkpointer: PostgresSaver
) -> None:
    """The admin action's safety net: a checkpointed id with no chat_threads row."""
    # Arrange
    thread_id = "drift-orphan"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = _empty_checkpoint()
    checkpointer.put(cast(Any, config), checkpoint, CheckpointMetadata(), {})

    # Act
    with conn.cursor() as cursor:
        cursor.execute(ORPHAN_THREAD_SQL)
        orphans = {row["thread_id"] for row in cursor.fetchall()}
    cursor = conn.cursor()
    cursor.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
    cursor.close()
    with conn.cursor() as cursor:
        cursor.execute(ORPHAN_THREAD_SQL)
        remaining = {row["thread_id"] for row in cursor.fetchall()}

    # Assert
    assert thread_id in orphans
    assert thread_id not in remaining
