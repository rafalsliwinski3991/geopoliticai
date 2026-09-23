"""Tests for the pre-launch purge management command (unit 7).

The `CREATE TABLE checkpoints` stub below exists only to exercise the
command's dry-run/apply branching; schema fidelity — the real columns and the
real schema — is `tests/integration_tests/test_db_agentic_schema.py`'s job.
"""

from django.db import connection

from chat.signals import CHECKPOINT_SCHEMA
from django.test import TransactionTestCase


class PurgePrelaunchThreadsTest(TransactionTestCase):
    """The pre-launch purge command: dry-run default, apply deletes (Q18)."""

    def call(self, *args: str) -> str:
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("purge_prelaunch_threads", *args, stdout=out)
        return out.getvalue()

    def test_missing_checkpointer_tables_are_reported_not_raised(self) -> None:
        # Arrange
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS checkpoints")

        # Act
        output = self.call()

        # Assert
        self.assertIn("missing", output)

    def setUp(self) -> None:
        """Each test starts without checkpointer tables in the constant's schema."""
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {CHECKPOINT_SCHEMA}.checkpoints")

    def test_dry_run_reports_and_changes_nothing(self) -> None:
        # Arrange
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {CHECKPOINT_SCHEMA}")
            cursor.execute(f"DROP TABLE IF EXISTS {CHECKPOINT_SCHEMA}.checkpoints")
            cursor.execute(
                f"CREATE TABLE {CHECKPOINT_SCHEMA}.checkpoints (thread_id TEXT NOT NULL)"
            )
            cursor.execute(
                f"INSERT INTO {CHECKPOINT_SCHEMA}.checkpoints (thread_id) VALUES ('ghost')"
            )
        try:
            # Act
            output = self.call("--dry-run")

            # Assert
            self.assertIn("DRY RUN", output)
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) AS n FROM {CHECKPOINT_SCHEMA}.checkpoints")
                self.assertEqual(cursor.fetchone()[0], 1)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE {CHECKPOINT_SCHEMA}.checkpoints")

    def test_apply_purges_the_orphaned_row(self) -> None:
        # Arrange
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {CHECKPOINT_SCHEMA}")
            cursor.execute(f"DROP TABLE IF EXISTS {CHECKPOINT_SCHEMA}.checkpoints")
            cursor.execute(
                f"CREATE TABLE {CHECKPOINT_SCHEMA}.checkpoints (thread_id TEXT NOT NULL)"
            )
            cursor.execute(
                f"INSERT INTO {CHECKPOINT_SCHEMA}.checkpoints (thread_id) VALUES ('ghost')"
            )
        try:
            # Act
            output = self.call("--apply")

            # Assert
            self.assertIn("Purged", output)
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) AS n FROM {CHECKPOINT_SCHEMA}.checkpoints")
                self.assertEqual(cursor.fetchone()[0], 0)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE {CHECKPOINT_SCHEMA}.checkpoints")
