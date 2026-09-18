"""Delete a user's checkpointed messages when the user is deleted.

The checkpointer's tables key on a bare `TEXT thread_id` with no foreign key
(verified in `langgraph/checkpoint/postgres/base.py` MIGRATIONS), so no Django
cascade reaches them. This runs inside the same transaction as the user delete,
before `chat_threads` rows are cascaded away and the thread ids become
unknowable.
"""

from django.conf import settings
from django.db import connection
from django.db.models.signals import pre_delete
from django.dispatch import receiver

# Child rows first: `checkpoint_writes` and `checkpoint_blobs` before
# `checkpoints`. There are no foreign keys between them, so the order is for
# readability, not integrity.
CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")


@receiver(pre_delete, sender=settings.AUTH_USER_MODEL)
def delete_checkpointed_messages(sender, instance, **kwargs) -> None:
    """Remove every checkpointer row belonging to this user's threads."""
    thread_ids = list(instance.threads.values_list("id", flat=True))
    if not thread_ids:
        return
    with connection.cursor() as cursor:
        for table in CHECKPOINT_TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE thread_id = ANY(%s)", [thread_ids])
