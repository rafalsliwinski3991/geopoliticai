"""Delete a user's checkpointed messages when the user is deleted.

The checkpointer's tables key on a bare `TEXT thread_id` with no foreign key
(verified in `langgraph/checkpoint/postgres/base.py` MIGRATIONS), so no Django
cascade reaches them. This runs inside the same transaction as the user delete,
before `chat_threads` rows are cascaded away and the thread ids become
unknowable.
"""

from django.conf import settings
from django.db import connection
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from .models import Thread

# LangGraph creates these tables and owns their DDL; this service only deletes
# from them. The schema is a separate constant so relocating them is one edit
# here and nothing downstream.
CHECKPOINT_SCHEMA = "agentic"
# Child rows first: `checkpoint_writes` and `checkpoint_blobs` before
# `checkpoints`. There are no foreign keys between them, so the order is for
# readability, not integrity.
CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")


def qualified(table: str) -> str:
    """Return `table` prefixed with the schema the checkpointer lives in."""
    return f"{CHECKPOINT_SCHEMA}.{table}"


def purge_statements(where: str) -> tuple[str, ...]:
    """Return the DELETE statements that clear one thread selection.

    Built here rather than inline so the integration suite executes these exact
    statements instead of a copy of them. A copy is what let the old guard pass
    while production was broken.
    """
    return tuple(f"DELETE FROM {qualified(t)} WHERE {where}" for t in CHECKPOINT_TABLES)


@receiver(pre_delete, sender=settings.AUTH_USER_MODEL)
def delete_checkpointed_messages(sender, instance, **kwargs) -> None:
    """Remove every checkpointer row belonging to this user's threads."""
    thread_ids = list(instance.threads.values_list("id", flat=True))
    if not thread_ids:
        return
    _purge_checkpoints("thread_id = ANY(%s)", [thread_ids])


@receiver(post_delete, sender=Thread)
def delete_thread_checkpoints(sender, instance, **kwargs) -> None:
    """Remove the checkpointer rows when a single thread is deleted.

    Covers the admin's per-object and bulk deletes (Django emits post_delete
    for every instance a queryset delete removes), so no `chat_threads` row
    can disappear while its checkpoints survive.
    """
    _purge_checkpoints("thread_id = %s", [instance.id])


def _purge_checkpoints(where: str, params: list) -> None:
    with connection.cursor() as cursor:
        for statement in purge_statements(where):
            cursor.execute(statement, params)
