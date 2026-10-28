"""The mandatory schema-drift guard on `db/web/sql.py`.

Django owns every table in `public` these statements touch; `agentic_backend/`
addresses them by name with raw psycopg and runs no migrations of its own. This
suite executes *every* statement in `db/web/sql.py` against a database migrated
by Django and set up by the checkpointer, so a renamed or dropped column fails
in CI instead of in production. It is one of a symmetric pair: the other side
is `web_backend/tests/integration_tests/test_db_agentic_schema.py`, which runs
the statements `web_backend` itself owns against the checkpointer's tables in
`agentic`.

Requires a real Postgres: `DATABASE_URL` pointing at a database that
(1) has been migrated by Django (`make migrate-web`) and (2) has the checkpointer
tables (`AsyncPostgresSaver.setup()` — the tests here run it themselves,
idempotently). The CI `cross-service-schema` job encodes that order; without
`DATABASE_URL` the suite fails; the ordinary unit run never collects it.

The deletion cascade is asserted against rows written by langgraph's own
`PostgresSaver`, using the exact DELETE statements the Django signal
(`web_backend/chat/signals.py`) runs. The signal itself is exercised by the
Django suite; what only an integration database can prove is that those
statements actually match the shape langgraph's writer produces.
"""

import os
import re
import time
from datetime import date, datetime, timezone
from typing import Any, Generator, cast

import pytest
from langgraph.checkpoint.base import CheckpointMetadata
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.base import MIGRATIONS
from psycopg import Connection, connect
from psycopg.rows import dict_row

from db.web import sql

# Fail, never skip: a skipped guard is a green CI job that tested nothing. The
# plain `pytest` run stays hermetic because `testpaths` excludes this suite.
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL must be set for integration tests")

# Every read statement in `db/web/sql.py`, with parameters that are valid but match
# nothing, so executing them against a real database proves the columns exist
# without depending on any row. Kept in lockstep by
# `test_every_statement_is_covered`.
NO_MATCH_PROBES: tuple[tuple[str, dict[str, Any]], ...] = (
    (sql.SELECT_THREAD_OWNER, {"thread_id": "drift-probe"}),
    (sql.SELECT_THREADS, {"user_id": 0}),
    (sql.SELECT_QUOTA_USED, {"user_id": 0, "day": date(1970, 1, 1)}),
    (sql.SELECT_IS_STAFF, {"user_id": 0}),
)

# Derived, never copied: the checkpointer tables keyed by thread_id, read out
# of the DDL langgraph itself ships. A rename or a new thread-keyed table in a
# version bump changes this automatically, which a typed-out tuple could not.
# `checkpoint_migrations` has no thread_id and is correctly excluded.
CASCADE_TABLES = tuple(
    name
    for name, body in re.findall(
        r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", "\n".join(MIGRATIONS), re.S
    )
    if "thread_id" in body
)
assert CASCADE_TABLES, "derived no cascade tables — langgraph's DDL shape changed"
# A local copy that proves these statements match the shape langgraph's writer
# produces. The statements `web_backend` actually runs are executed by
# `web_backend/tests/integration_tests/test_db_agentic_schema.py`, which is the
# guard against drift between the two. Schema-qualified exactly as
# `purge_statements()` emits them, so they resolve without search_path.
CASCADE_SQL = tuple(
    f"DELETE FROM agentic.{table} WHERE thread_id = ANY(%s)" for table in CASCADE_TABLES
)
# A copy of the purge command's orphan query, for the same shape check; the
# web-side suite executes the command's own `ORPHAN_IDS_SQL`.
ORPHAN_THREAD_SQL = """
SELECT DISTINCT thread_id
FROM agentic.checkpoints
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


# These fixtures open their own connections and inherit nothing from api/app.py's
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
        # Without the `agentic` schema, setup() would plant its tables in
        # `public` and the next real boot of agentic-backend would refuse.
        row = fetch_one(raw, "SELECT current_schema() AS target")
        assert row["target"] == "agentic", "run `make migrate-agentic` first"
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


SQL_KEYWORDS = ("SELECT", "INSERT", "UPDATE", "DELETE")

# Write statements cannot use a no-match probe: executing a DELETE against
# nothing proves nothing. Each is named here with the test that exercises it,
# and `test_every_statement_is_covered` fails if that test no longer exists.
EXERCISED_WRITES = {
    "UPSERT_THREAD": "test_upsert_thread_creates_once_and_the_owner_is_read_back",
    "INCREMENT_QUOTA": "test_increment_quota_upserts_increments_and_caps",
    "INCREMENT_SITE_QUOTA": "test_increment_site_quota_upserts_increments_and_caps",
    "REFUND_QUOTA": "test_refund_quota_gives_back_the_cost",
}

# Fixed past days for the refund tests: never today's live counters, and the
# per-test `user_id` fixture deletes every `quota` row it created.
DAY = date(2026, 10, 16)
NEXT_DAY = date(2026, 10, 17)


def _sql_constants() -> dict[str, str]:
    """Every module-level SQL statement in db/web/sql.py, by name.

    Keyed on content, not on a name prefix: the prefix filter is what let write
    statements sit outside the guard entirely.
    """
    return {
        name: value
        for name, value in vars(sql).items()
        if name.isupper()
        and isinstance(value, str)
        and any(keyword in value.upper() for keyword in SQL_KEYWORDS)
    }


def test_every_statement_is_covered() -> None:
    """Any new statement in db/web/sql.py without a test fails here."""
    # Arrange
    statements = _sql_constants()
    assert statements, "no SQL constants found — the detector is broken"
    # Act
    probed = {statement for statement, _ in NO_MATCH_PROBES}
    covered = {name for name, value in statements.items() if value in probed} | set(
        EXERCISED_WRITES
    )
    # Assert
    assert set(statements) == covered
    # Each registry entry must name a test that exists in this module.
    assert all(callable(globals().get(test)) for test in EXERCISED_WRITES.values())


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
        conn,
        sql.INCREMENT_QUOTA,
        {"user_id": user_id, "day": day, "limit": 2, "cost": 1},
    )["used"]
    second = fetch_one(
        conn,
        sql.INCREMENT_QUOTA,
        {"user_id": user_id, "day": day, "limit": 2, "cost": 1},
    )["used"]
    capped = fetch_one(
        conn,
        sql.INCREMENT_QUOTA,
        {"user_id": user_id, "day": day, "limit": 2, "cost": 1},
    )
    # Assert
    assert (first, second) == (1, 2)
    # The WHERE on the conflict target decides affordability: no row at the cap.
    assert capped is None


def test_increment_site_quota_upserts_increments_and_caps(
    conn: Connection[dict[str, Any]],
) -> None:
    """The site-wide conditional upsert, both ON CONFLICT branches, for real.

    Runs the raw statement on a fixed past day, never today's live counter.
    """
    # Arrange
    day = date(1971, 1, 1)
    # Act
    try:
        first = fetch_one(
            conn, sql.INCREMENT_SITE_QUOTA, {"day": day, "limit": 2, "cost": 1}
        )["used"]
        second = fetch_one(
            conn, sql.INCREMENT_SITE_QUOTA, {"day": day, "limit": 2, "cost": 1}
        )["used"]
        capped = fetch_one(
            conn, sql.INCREMENT_SITE_QUOTA, {"day": day, "limit": 2, "cost": 1}
        )
        used = fetch_one(conn, "SELECT used FROM site_quota WHERE day = %s", (day,))[
            "used"
        ]
    finally:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM site_quota WHERE day = %s", (day,))
    # Assert
    assert (first, second) == (1, 2)
    assert capped is None
    assert used == 2


def test_increment_quota_spends_the_whole_cost_or_nothing(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    """A cost that does not all fit buys nothing; a partial balance never spends."""
    # Act + Assert: raw statements only, like the existing upsert test — the
    # helper is pinned to today's live counters, which this must never touch.
    first = fetch_one(
        conn,
        sql.INCREMENT_QUOTA,
        {"user_id": user_id, "day": date.today(), "limit": 5, "cost": 3},
    )["used"]
    refused = fetch_one(
        conn,
        sql.INCREMENT_QUOTA,
        {"user_id": user_id, "day": date.today(), "limit": 5, "cost": 3},
    )
    left = fetch_one(
        conn,
        "SELECT used FROM quota WHERE user_id = %s AND day = %s",
        (user_id, date.today()),
    )["used"]
    last = fetch_one(
        conn,
        sql.INCREMENT_QUOTA,
        {"user_id": user_id, "day": date.today(), "limit": 5, "cost": 2},
    )["used"]
    assert first == 3
    assert refused is None
    assert left == 3
    assert last == 5


def test_increment_site_quota_spends_the_whole_cost_or_nothing(
    conn: Connection[dict[str, Any]],
) -> None:
    """The site-wide whole-cost rule, on the fixed day, never today's row."""
    # Arrange
    day = date(1971, 1, 2)
    try:
        # Act + Assert
        first = fetch_one(
            conn, sql.INCREMENT_SITE_QUOTA, {"day": day, "limit": 5, "cost": 3}
        )["used"]
        refused = fetch_one(
            conn, sql.INCREMENT_SITE_QUOTA, {"day": day, "limit": 5, "cost": 3}
        )
        last = fetch_one(
            conn, sql.INCREMENT_SITE_QUOTA, {"day": day, "limit": 5, "cost": 2}
        )["used"]
    finally:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM site_quota WHERE day = %s", (day,))
    assert first == 3
    assert refused is None
    assert last == 5


def test_refund_quota_gives_back_the_cost(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    """A refund subtracts exactly the cost from the day it names."""
    # Arrange: charged 20 on DAY, the way `INCREMENT_QUOTA` writes it.
    run(
        conn,
        sql.INCREMENT_QUOTA,
        {"user_id": user_id, "day": DAY, "limit": 50, "cost": 20},
    )

    # Act
    run(conn, sql.REFUND_QUOTA, {"user_id": user_id, "day": DAY, "cost": 20})

    # Assert
    used = fetch_one(
        conn,
        "SELECT used FROM quota WHERE user_id = %s AND day = %s",
        (user_id, DAY),
    )["used"]
    assert used == 0


def test_a_partial_refund_gives_back_part_of_the_charge(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    """A refund subtracts the cost, it does not zero the day: a charge of 20
    with 5 refunded leaves 15, which a `used = 0` write would not show."""
    # Arrange: charged 20 on DAY.
    run(
        conn,
        sql.INCREMENT_QUOTA,
        {"user_id": user_id, "day": DAY, "limit": 50, "cost": 20},
    )

    # Act: refund part of it.
    run(conn, sql.REFUND_QUOTA, {"user_id": user_id, "day": DAY, "cost": 5})

    # Assert
    used = fetch_one(
        conn,
        "SELECT used FROM quota WHERE user_id = %s AND day = %s",
        (user_id, DAY),
    )["used"]
    assert used == 15


def test_a_refund_never_goes_below_zero(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    """`GREATEST` floors the count at zero: an admin may have reset the row
    since the charge, and Django's `used` is a PositiveIntegerField."""
    # Arrange: charged 20, then an admin reset the row to 5.
    run(
        conn,
        sql.INCREMENT_QUOTA,
        {"user_id": user_id, "day": DAY, "limit": 50, "cost": 20},
    )
    run(
        conn,
        "UPDATE quota SET used = 5 WHERE user_id = %s AND day = %s",
        (user_id, DAY),
    )

    # Act: refund the original 20 anyway.
    run(conn, sql.REFUND_QUOTA, {"user_id": user_id, "day": DAY, "cost": 20})

    # Assert
    used = fetch_one(
        conn,
        "SELECT used FROM quota WHERE user_id = %s AND day = %s",
        (user_id, DAY),
    )["used"]
    assert used == 0


def test_a_refund_touches_only_the_charge_day(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    """The refund's WHERE names the day, so the next day's row keeps its count."""
    # Arrange: rows for two consecutive days.
    run(
        conn,
        sql.INCREMENT_QUOTA,
        {"user_id": user_id, "day": DAY, "limit": 50, "cost": 20},
    )
    run(
        conn,
        sql.INCREMENT_QUOTA,
        {"user_id": user_id, "day": NEXT_DAY, "limit": 50, "cost": 20},
    )

    # Act
    run(conn, sql.REFUND_QUOTA, {"user_id": user_id, "day": DAY, "cost": 20})

    # Assert
    charge_day_used = fetch_one(
        conn,
        "SELECT used FROM quota WHERE user_id = %s AND day = %s",
        (user_id, DAY),
    )["used"]
    next_day_used = fetch_one(
        conn,
        "SELECT used FROM quota WHERE user_id = %s AND day = %s",
        (user_id, NEXT_DAY),
    )["used"]
    assert charge_day_used == 0
    assert next_day_used == 20


def test_a_refund_touches_only_that_user(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    """The refund's WHERE names the user, so nobody else's count moves."""
    # Arrange: a second user, charged the same day as the fixture's user.
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
            (f"drift-other-{os.getpid()}-{time.time_ns()}@example.com",),
        )
        other_id = cast(Any, cursor.fetchone())["id"]
    try:
        run(
            conn,
            sql.INCREMENT_QUOTA,
            {"user_id": user_id, "day": DAY, "limit": 50, "cost": 20},
        )
        run(
            conn,
            sql.INCREMENT_QUOTA,
            {"user_id": other_id, "day": DAY, "limit": 50, "cost": 20},
        )

        # Act: refund only the fixture's user.
        run(conn, sql.REFUND_QUOTA, {"user_id": user_id, "day": DAY, "cost": 20})

        # Assert
        own_used = fetch_one(
            conn,
            "SELECT used FROM quota WHERE user_id = %s AND day = %s",
            (user_id, DAY),
        )["used"]
        other_used = fetch_one(
            conn,
            "SELECT used FROM quota WHERE user_id = %s AND day = %s",
            (other_id, DAY),
        )["used"]
        assert own_used == 0
        assert other_used == 20
    finally:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM quota WHERE user_id = %s", (other_id,))
            cursor.execute("DELETE FROM users_user WHERE id = %s", (other_id,))


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


def test_columns_are_wide_enough_for_the_constants_that_assume_them(
    conn: Connection[dict[str, Any]], user_id: int
) -> None:
    """A narrowed Django column fails here, not mid-stream in claim_thread.

    Every other probe uses a short value, so a narrowed column passes all of
    them. This one writes exactly what the constants promise the columns hold.
    """
    # Arrange
    thread_id = "d" * sql.MAX_THREAD_ID_LENGTH
    title = "t" * sql.MAX_TITLE_LENGTH
    # Act
    make_thread(conn, thread_id, user_id, title)
    row = fetch_one(
        conn,
        "SELECT id, title FROM chat_threads WHERE id = %(id)s",
        {"id": thread_id},
    )
    # Assert: round-tripped intact, not silently truncated.
    assert row["id"] == thread_id
    assert row["title"] == title


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


@pytest.mark.integration
def test_the_store_tables_land_in_agentic(url: str) -> None:
    """The store's tables are LangGraph-owned like the checkpointer's: created
    by `AsyncPostgresStore.setup()` on the shared pool, in the `agentic` schema,
    and never in `public`."""
    from langgraph.store.postgres import PostgresStore

    with connect(
        url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options=SEARCH_PATH_OPTION,
    ) as raw:
        row = fetch_one(raw, "SELECT current_schema() AS target")
        assert row["target"] == "agentic", "run `make migrate-agentic` first"
        PostgresStore(raw).setup()
        landed = fetch_one(
            raw,
            "SELECT to_regclass('agentic.store') AS store,"
            " to_regclass('agentic.store_migrations') AS migrations,"
            " to_regclass('public.store') AS stray",
        )
        assert landed["store"] is not None
        assert landed["migrations"] is not None
        assert landed["stray"] is None
