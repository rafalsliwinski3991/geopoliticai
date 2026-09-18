"""Tests for the pre-launch purge management command (unit 7)."""

from django.db import connection
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

    def test_dry_run_reports_and_changes_nothing(self) -> None:
        # Arrange
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS checkpoints")
            cursor.execute("CREATE TABLE checkpoints (thread_id TEXT NOT NULL)")
            cursor.execute("INSERT INTO checkpoints (thread_id) VALUES ('ghost')")
        try:
            # Act
            output = self.call("--dry-run")

            # Assert
            self.assertIn("DRY RUN", output)
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS n FROM checkpoints")
                self.assertEqual(cursor.fetchone()[0], 1)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE checkpoints")

    def test_apply_purges_the_orphaned_row(self) -> None:
        # Arrange
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS checkpoints")
            cursor.execute("CREATE TABLE checkpoints (thread_id TEXT NOT NULL)")
            cursor.execute("INSERT INTO checkpoints (thread_id) VALUES ('ghost')")
        try:
            # Act
            output = self.call("--apply")

            # Assert
            self.assertIn("Purged", output)
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS n FROM checkpoints")
                self.assertEqual(cursor.fetchone()[0], 0)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DROP TABLE checkpoints")
