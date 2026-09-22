"""The mandatory schema-drift guard.

Django owns every table in `public` these statements touch; `agentic_backend/` addresses
them by name with raw psycopg and runs no migrations of its own. This suite
executes *every* statement in `db/web/sql.py` against a database migrated by
Django and set up by the checkpointer, so a renamed or dropped column fails in
CI instead of in production.

Requires a real Postgres: `DATABASE_URL` pointing at a database that
(1) has been migrated by Django (`make migrate-web`) and (2) has the checkpointer
tables (`AsyncPostgresSaver.setup()` — the tests here run it themselves,
idempotently). The CI `cross-service-schema` job encodes that order; without
`DATABASE_URL` the suite skips so the ordinary unit run stays hermetic.

The deletion cascade is asserted against rows written by langgraph's own
`PostgresSaver`, using the exact DELETE statements the Django signal
(`web_backend/chat/signals.py`) runs. The signal itself is exercised by the
Django suite; what only an integration database can prove is that those
statements actually match the shape langgraph's writer produces.
"""

import os
import time
from datetime import date, datetime, timezone
from typing import Any, Generator, cast

import pytest
from langgraph.checkpoint.base import CheckpointMetadata
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection, connect
from psycopg.rows import dict_row

from db.web import sql

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="needs a real Postgres (make test-integration)",
)

# Every read statement in `db/web/sql.py`, with parameters that are valid but match
# nothing, so executing them against a real database proves the columns exist
# without depending on any row. Kept in lockstep by
# `test_every_read_statement_has_a_probe`.
NO_MATCH_PROBES: tuple[tuple[str, dict[str, Any]], ...] = (
    (sql.SELECT_THREAD_OWNER, {"thread_id": "drift-probe"}),
    (sql.SELECT_THREADS, {"user_id": 0}),
    (sql.SELECT_QUOTA_USED, {"user_id": 0, "day": date(1970, 1, 1)}),
    (sql.SELECT_IS_STAFF, {"user_id": 0}),
)

CASCADE_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")
# The DELETE statements `web_backend/chat/signals.py` runs, mirrored here so a
# rename on either side fails the other side's guard.
CASCADE_SQL = tuple(
    f"DELETE FROM {table} WHERE thread_id = ANY(%s)" for table in CASCADE_TABLES
)
# The orphan-check query `web_backend/chat/management/commands/purge_prelaunch_threads.py`
# runs verbatim before purging the checkpointer rows.
ORPHAN_THREAD_SQL = """
SELECT DISTINCT thread_id
FROM checkpoints
WHERE thread_id NOT IN (SELECT id FROM chat_threads)
"""


def run(conn: Connection[dict[str, Any]], statement: str, params: Any = None) -> None:
    """Execute one statement on its own cursor."""
    with conn.cursor() as cursor:
        cursor.execute(statement, params)


def fetch_one(
    conn: Connection[dict[str, Any]], statement: str, params: Any = None
) -> Any:
    """Execute one statement and return its single row, or None."""
    with conn.cursor() as cursor:
        cursor.execute(statement, params)
        return cursor.fetchone()


def make_thread(
    conn: Connection[dict[str, Any]], thread_id: str, user_id: int, title: str = ""
) -> None:
    """Insert one `chat_threads` row through the statement under test."""
    run(
        conn,
        sql.UPSERT_THREAD,
        {"thread_id": thread_id, "user_id": user_id, "title": title},
    )


@pytest.fixture(scope="module")
def url() -> str:
    return os.environ["DATABASE_URL"]


# These fixtures open their own connections and inherit nothing from api.py's
# pool, so they must set the same search_path or setup() will create a second
# set of checkpointer tables in `public` and the tripwire will fire on the next
# real boot.
SEARCH_PATH_OPTION = "-c search_path=agentic,public"


@pytest.fixture(scope="module")
def conn(url: str) -> Generator[Connection[dict[str, Any]], None, None]:
    """One autocommit connection per module; tests clean up after themselves."""
    with connect(
        url, autocommit=True, row_factory=dict_row, options=SEARCH_PATH_OPTION
    ) as connection:
        yield connection


@pytest.fixture(scope="module")
def checkpointer(url: str) -> Generator[PostgresSaver, None, None]:
    """The checkpointer's tables, created by its own `setup()` if missing.

    Same kwargs `PostgresSaver.from_conn_string` sets
    (`langgraph/checkpoint/postgres/__init__.py:68-70`). `setup()` does not
    depend on `row_factory` — every branch of `_cursor()` sets `dict_row`
    per-cursor — but a fixture standing in for `from_conn_string` should not
    silently diverge from it, and `prepare_threshold=0` matters.
    """
    with connect(
        url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options=SEARCH_PATH_OPTION,
    ) as raw:
        saver = PostgresSaver(raw)
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
    # Act + Assert: every probe must execute as a valid, no-match query.
    for statement, params in NO_MATCH_PROBES:
        with conn.cursor() as cursor:
            cursor.execute(statement, params)
            cursor.fetchall()


def test_every_read_statement_has_a_probe() -> None:
    """A new SELECT_ in db/sql.py without a probe fails here, not in production."""
    # Arrange
    read_statements = {
        value for name, value in vars(sql).items() if name.startswith("SELECT_")
    }
    # Act
    probed = {statement for statement, _ in NO_MATCH_PROBES}
    # Assert
    assert read_statements == probed


def test_upsert_thread_creates_once_and_the_owner_is_read_back(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    # Act: the second upsert is the idempotent-conflict update.
    make_thread(conn, "drift-1", user_id, "NATO")
    make_thread(conn, "drift-1", user_id, "NATO again")
    row = fetch_one(conn, sql.SELECT_THREAD_OWNER, {"thread_id": "drift-1"})
    title = fetch_one(conn, "SELECT title FROM chat_threads WHERE id = 'drift-1'")[
        "title"
    ]
    # Assert
    assert row["user_id"] == user_id
    assert title == "NATO"


def test_select_threads_returns_the_serialized_columns(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    # Arrange
    make_thread(conn, "drift-2", user_id, "Lithuania")
    # Act
    with conn.cursor() as cursor:
        cursor.execute(sql.SELECT_THREADS, {"user_id": user_id})
        rows = cursor.fetchall()
    # Assert
    row = next(r for r in rows if r["id"] == "drift-2")
    assert row["title"] == "Lithuania"
    assert row["created_at"] is not None


def test_increment_quota_upserts_increments_and_caps(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    """The conditional atomic upsert, both ON CONFLICT branches, for real."""
    # Arrange
    day = date.today()
    # Act
    first = fetch_one(
        conn, sql.INCREMENT_QUOTA, {"user_id": user_id, "day": day, "limit": 2}
    )["used"]
    second = fetch_one(
        conn, sql.INCREMENT_QUOTA, {"user_id": user_id, "day": day, "limit": 2}
    )["used"]
    capped = fetch_one(
        conn, sql.INCREMENT_QUOTA, {"user_id": user_id, "day": day, "limit": 2}
    )
    # Assert
    assert (first, second) == (1, 2)
    # The WHERE on the conflict target decides affordability: no row at the cap.
    assert capped is None


def test_deleting_a_user_cascades_into_the_checkpointer_tables(
    conn: Connection[dict[str, Any]], checkpointer: PostgresSaver, user_id: int
) -> None:
    """No FK reaches the checkpointer tables; the signal's DELETEs must.

    Mirrors Django's delete order honestly: Django emulates FK cascades in the
    ORM, so the sequence the production delete follows is the signal's
    checkpointer DELETEs (pre_delete), then the ORM's chat_threads/quota
    cascade, then the user row.
    """
    thread_id = "drift-3"
    # Arrange: a Django thread plus rows written by langgraph's own saver.
    make_thread(conn, thread_id, user_id, "")
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = _empty_checkpoint()
    saved_config = checkpointer.put(
        cast(Any, config), checkpoint, CheckpointMetadata(), {}
    )
    checkpointer.put_writes(saved_config, [("channel", "value")], "task-1")

    # Act: the signal fires on pre_delete, inside the user-delete transaction.
    with conn.cursor() as cursor:
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
        for table in CASCADE_TABLES:
            cursor.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE thread_id = %s",
                (thread_id,),
            )
            assert cast(Any, cursor.fetchone())["n"] == 0, table


def test_the_site_wide_sentinel_can_be_incremented(
    conn: Connection[dict[str, Any]],
) -> None:
    """The reserved sentinel row makes user_id 0 a valid quota spender.

    A missing sentinel row would turn every research turn into a mid-stream
    500: the per-user increment succeeds first, then the site-wide insert hits
    the `quota.user_id` foreign key. The counter's prior value is restored, so
    the test never resets a shared database's site-wide ceiling.
    """
    # Arrange
    day = date.today()
    with conn.cursor() as cursor:
        cursor.execute("SELECT used FROM quota WHERE user_id = 0 AND day = %s", (day,))
        prior = cast(Any, cursor.fetchone())
    prior_used = prior["used"] if prior else None
    # Act
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql.INCREMENT_QUOTA,
                {"user_id": 0, "day": day, "limit": 10**9},
            )
            spent = cast(Any, cursor.fetchone())
        # Assert
        assert spent is not None and spent["used"] >= 1
    finally:
        # Restore: never reset a shared database's site-wide ceiling.
        with conn.cursor() as cursor:
            if prior_used is None:
                cursor.execute(
                    "DELETE FROM quota WHERE user_id = 0 AND day = %s", (day,)
                )
            else:
                cursor.execute(
                    "UPDATE quota SET used = %s WHERE user_id = 0 AND day = %s",
                    (prior_used, day),
                )
        # Assert: the restore left the counter exactly as it was found.
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT used FROM quota WHERE user_id = 0 AND day = %s", (day,)
            )
            restored = cast(Any, cursor.fetchone())
        if prior_used is None:
            # The counter did not exist today; the test leaves it that way.
            assert restored is None
        else:
            assert restored is not None and restored["used"] == prior_used


def test_orphan_query_reports_a_checkpointed_id_and_purges_cleanly(
    conn: Connection[dict[str, Any]], checkpointer: PostgresSaver
) -> None:
    """The admin action's safety net: a checkpointed id with no chat_threads row."""
    # Arrange
    thread_id = "drift-orphan"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
    checkpoint = _empty_checkpoint()
    checkpointer.put(cast(Any, config), checkpoint, CheckpointMetadata(), {})
    # Act + Assert: the query reports it, then a purge makes it vanish.
    with conn.cursor() as cursor:
        cursor.execute(ORPHAN_THREAD_SQL)
        assert thread_id in {row["thread_id"] for row in cursor.fetchall()}
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))
        cursor.execute(ORPHAN_THREAD_SQL)
        assert thread_id not in {row["thread_id"] for row in cursor.fetchall()}
