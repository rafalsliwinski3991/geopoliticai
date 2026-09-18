"""Delete checkpointer rows whose thread has no chat_threads row (Q18).

Pre-launch, conversations lived only in the checkpointer with no identity
attached; every one of them is an orphan once the per-user schema exists. This
is a one-time, one-way-door cleanup: deleted rows are recoverable only from a
`pg_dump`, so the default is `--dry-run` and `--apply` must be passed
deliberately. The escape hatch the plan records (§3.1) stays available: a
manual `UPDATE chat_threads SET user_id = ...` for a known thread id is safe;
only *automatic* claiming was the vulnerability.
"""

from django.core.management.base import BaseCommand
from django.db import connection

# Child rows first, for readability rather than integrity — there are no
# foreign keys between them.
CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")

ORPHAN_IDS_SQL = """
SELECT DISTINCT thread_id
FROM checkpoints
WHERE thread_id NOT IN (SELECT id FROM chat_threads)
"""


def _table_exists(cursor, table: str) -> bool:
    """Report whether `table` exists, via to_regclass.

    An existence read is what tolerates a partial schema; catching
    ProgrammingError instead would also swallow privilege failures and, inside
    `transaction.atomic`, the aborted-transaction state a failed statement
    leaves behind.
    """
    cursor.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
    return bool(cursor.fetchone()[0])


def orphan_thread_ids() -> list[str] | None:
    """Return orphaned thread ids, or None when the checkpointer tables are missing."""
    with connection.cursor() as cursor:
        if not (
            _table_exists(cursor, "checkpoints") and _table_exists(cursor, "chat_threads")
        ):
            return None
        cursor.execute(ORPHAN_IDS_SQL)
        return [row[0] for row in cursor.fetchall()]


def purge_orphans(orphans: list[str]) -> None:
    """Delete the checkpointer rows belonging to the orphaned threads.

    Missing sibling tables (a partial schema) are skipped; any other database
    failure propagates, because the command must never report a purge that did
    not execute.
    """
    with connection.cursor() as cursor:
        for table in CHECKPOINT_TABLES:
            if not _table_exists(cursor, table):
                continue
            cursor.execute(f"DELETE FROM {table} WHERE thread_id = ANY(%s)", [orphans])


class Command(BaseCommand):
    """Purge pre-launch checkpointer rows that no thread row can name."""

    help = __doc__

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted without writing (the default).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Delete the rows. Without this flag nothing is written.",
        )

    def handle(self, *args, **options) -> None:
        orphans = orphan_thread_ids()
        if orphans is None:
            self.stdout.write(
                "The checkpointer tables are missing; nothing to purge here."
            )
            return
        if not orphans:
            self.stdout.write("No orphaned checkpointer threads. Nothing to do.")
            return
        for thread_id in orphans:
            self.stdout.write(f"  orphaned: {thread_id}")
        if not options["apply"]:
            self.stdout.write(
                f"{len(orphans)} orphaned thread id(s). DRY RUN — pass --apply to delete."
            )
            return
        purge_orphans(orphans)
        self.stdout.write(f"Purged checkpointer rows for {len(orphans)} thread id(s).")
