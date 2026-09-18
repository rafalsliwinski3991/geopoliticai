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
from django.db.utils import ProgrammingError

# Child rows first, for readability rather than integrity — there are no
# foreign keys between them.
CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")

ORPHAN_IDS_SQL = """
SELECT DISTINCT thread_id
FROM checkpoints
WHERE thread_id NOT IN (SELECT id FROM chat_threads)
"""


def orphan_thread_ids() -> list[str] | None:
    """Return orphaned thread ids, or None when the checkpointer tables are missing."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(ORPHAN_IDS_SQL)
            return [row[0] for row in cursor.fetchall()]
    except ProgrammingError:
        return None


def purge_orphans(orphans: list[str]) -> None:
    """Delete the checkpointer rows belonging to the orphaned threads.

    Missing sibling tables (a partial schema) are tolerated: the command is a
    cleanup tool, and a half-migrated database is exactly when it is needed.
    """
    with connection.cursor() as cursor:
        for table in CHECKPOINT_TABLES:
            try:
                cursor.execute(f"DELETE FROM {table} WHERE thread_id = ANY(%s)", [orphans])
            except ProgrammingError:
                continue


class Command(BaseCommand):
    """Purge pre-launch checkpointer rows that no thread row can name."""

    help = __doc__

    def add_arguments(self, parser) -> None:
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
