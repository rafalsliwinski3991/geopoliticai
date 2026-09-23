"""The mandatory guard on the schema this service does NOT own.

`web_backend/` owns no part of the checkpointer's schema: LangGraph creates
those tables and `agentic_backend` runs their setup. This service deletes from
them anyway, because `checkpoints.thread_id` references `chat_threads.id` only
logically — there is no foreign key, so no Django cascade reaches them, and a
silent failure here leaves user message content in the database after account
deletion.

These tests execute the real statements from `chat/signals.py`. They do not
copy them: `purge_statements()` is imported, so a change there is a change
here.

Django's test runner builds a fresh `test_` database containing only Django's
migrations, so the checkpointer tables do not exist in it. These tests
deliberately bypass `django.db.connection` and open their own psycopg
connection to the development database, using the same POSTGRES_* variables
Django itself reads. They clean up after themselves.

    make test-web-integration
"""

import os
import unittest
import uuid

import psycopg
from django.test import TestCase, tag

from chat.signals import CHECKPOINT_SCHEMA, CHECKPOINT_TABLES, purge_statements
from chat.management.commands.purge_prelaunch_threads import ORPHAN_IDS_SQL

# Unique per run: this suite writes to the shared development database, and
# `Thread.id` accepts any string, so a fixed id could name a real conversation
# whose checkpoints `_purge()` would then delete.
THREAD_ID = f"web-drift-probe-{uuid.uuid4().hex}"

# Minimal well-formed rows. Written out column by column on purpose: if an
# upstream version adds a NOT NULL column, these inserts fail here rather than
# in a user's account deletion.
INSERTS = {
    "checkpoints": (
        "INSERT INTO {t} (thread_id, checkpoint_ns, checkpoint_id, checkpoint, metadata)"
        " VALUES (%s, '', 'probe', '{{}}'::jsonb, '{{}}'::jsonb)"
    ),
    "checkpoint_blobs": (
        "INSERT INTO {t} (thread_id, checkpoint_ns, channel, version, type)"
        " VALUES (%s, '', 'probe', '1', 'empty')"
    ),
    "checkpoint_writes": (
        "INSERT INTO {t} (thread_id, checkpoint_ns, checkpoint_id, task_id, idx,"
        " channel, blob) VALUES (%s, '', 'probe', 'task', 0, 'probe', ''::bytea)"
    ),
}


def _checkpointer_tables_present() -> bool:
    """Report whether this database has been given the checkpointer's tables.

    NOT a POSTGRES_DB check: that variable is set in both CI jobs, so it cannot
    discriminate between the database that has had `setup()` run against it and
    the one that has not. Asking the database directly means a runner without
    the tables skips these tests instead of erroring on a missing relation.
    Only an absent table skips: a connection or authentication failure raises,
    so a misconfigured CI job fails instead of going green with zero tests.
    """
    with psycopg.connect(_connection_string(), autocommit=True) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass(%s)", [f"{CHECKPOINT_SCHEMA}.checkpoints"]
            )
            return cursor.fetchone()[0] is not None


def _connection_string() -> str:
    """Build the connection string from the same variables Django's settings read."""
    return (
        f"dbname={os.environ['POSTGRES_DB']} user={os.environ['POSTGRES_USER']}"
        f" password={os.environ['POSTGRES_PASSWORD']}"
        f" host={os.getenv('POSTGRES_HOST', 'postgres')}"
        f" port={os.getenv('POSTGRES_PORT', '5432')}"
    )


@tag("integration")
@unittest.skipUnless(
    _checkpointer_tables_present(), "needs a Postgres with the checkpointer tables"
)
class CheckpointerScheduleTest(TestCase):
    """The delete path this service runs against LangGraph's tables."""

    def setUp(self) -> None:
        self.conn = psycopg.connect(_connection_string(), autocommit=True)
        self.addCleanup(self.conn.close)
        self.addCleanup(self._purge)
        self._purge()

    def _purge(self) -> None:
        with self.conn.cursor() as cursor:
            for statement in purge_statements("thread_id = %s"):
                cursor.execute(statement, [THREAD_ID])

    def _seed(self) -> None:
        with self.conn.cursor() as cursor:
            for table, template in INSERTS.items():
                cursor.execute(
                    template.format(t=f"{CHECKPOINT_SCHEMA}.{table}"), [THREAD_ID]
                )

    def _counts(self) -> dict[str, int]:
        counts = {}
        with self.conn.cursor() as cursor:
            for table in CHECKPOINT_TABLES:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {CHECKPOINT_SCHEMA}.{table}"
                    " WHERE thread_id = %s",
                    [THREAD_ID],
                )
                counts[table] = cursor.fetchone()[0]
        return counts

    def test_purge_statements_clear_every_checkpointer_table(self) -> None:
        """The real DELETEs, against the real tables, must remove every row."""
        # Arrange
        self._seed()
        self.assertEqual(set(self._counts().values()), {1})
        # Act
        self._purge()
        # Assert
        self.assertEqual(self._counts(), dict.fromkeys(CHECKPOINT_TABLES, 0))

    def test_orphan_query_executes_against_the_real_schema(self) -> None:
        """The purge command's safety net must parse and run."""
        # Arrange
        self._seed()
        # Act
        with self.conn.cursor() as cursor:
            cursor.execute(ORPHAN_IDS_SQL)
            orphans = {row[0] for row in cursor.fetchall()}
        # Assert: seeded with no chat_threads row, so it is an orphan.
        self.assertIn(THREAD_ID, orphans)

    def test_every_thread_keyed_table_is_one_we_delete_from(self) -> None:
        """A new thread_id-keyed table upstream is a GDPR hole; fail here.

        Derived from the live database rather than from langgraph, which this
        service does not depend on, and rather than from a copy of the list.
        """
        # Act
        with self.conn.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT table_name FROM information_schema.columns"
                " WHERE table_schema = %s AND column_name = 'thread_id'",
                [CHECKPOINT_SCHEMA],
            )
            found = {row[0] for row in cursor.fetchall()}
        # Assert
        self.assertEqual(found, set(CHECKPOINT_TABLES))
