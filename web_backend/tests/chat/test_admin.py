"""Tests for the admin actions over the chat_threads table (unit 4)."""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from chat.management.commands.purge_prelaunch_threads import orphan_thread_ids
from chat.signals import CHECKPOINT_SCHEMA

User = get_user_model()


class OrphanQueryTest(TransactionTestCase):
    """The orphan-check SQL runs and reports thread ids absent from chat_threads.

    The checkpointer's `checkpoints` table does not exist in a fresh test
    database, so a minimal stand-in is created for the query-shape test; the
    real table's shape is validated by unit 6's drift test.
    """

    def test_orphan_query_reports_missing_chat_threads(self) -> None:
        # Arrange
        user = User.objects.create_user(email="o@example.com", password="x-not-used-1")
        user.threads.create(id="known")

        # Act
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {CHECKPOINT_SCHEMA}")
            cursor.execute(
                f"CREATE TABLE {CHECKPOINT_SCHEMA}.checkpoints (thread_id TEXT NOT NULL)"
            )
            cursor.execute(
                f"INSERT INTO {CHECKPOINT_SCHEMA}.checkpoints (thread_id) VALUES ('ghost')"
            )
        orphans = orphan_thread_ids()

        # Assert
        self.assertEqual(orphans, ["ghost"])

    def test_missing_checkpointer_table_is_reported_not_raised(self) -> None:
        # Act
        # A test database has no checkpointer tables; the admin action must
        # degrade to a warning, not a 500.
        orphans = orphan_thread_ids()

        # Assert
        self.assertEqual(orphans, None)
