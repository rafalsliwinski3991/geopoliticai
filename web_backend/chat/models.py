"""Application tables Django owns and the FastAPI service reads and writes.

`agentic_backend/` addresses these tables by name with raw psycopg (Q10). A rename here is
a runtime break there that neither an import nor Django's own tests can catch,
which is why `agentic_backend/tests/integration_tests/test_schema_drift.py` is mandatory
(brainstorm flag 4). Change a column name here and that test must change with
it, in the same stack.
"""

from django.conf import settings
from django.db import models

# The thread id the browser mints and the LangGraph checkpointer keys on. TEXT,
# not UUID: `api.RunPipelineRequest` accepts any `[A-Za-z0-9_-]{1,100}`.
MAX_THREAD_ID_LENGTH = 100
MAX_TITLE_LENGTH = 60


class Thread(models.Model):
    """One conversation, owned by one user."""

    id = models.CharField(primary_key=True, max_length=MAX_THREAD_ID_LENGTH)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="threads"
    )
    title = models.CharField(max_length=MAX_TITLE_LENGTH, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_threads"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title or self.id


class Quota(models.Model):
    """One user's research-turn count for one day (Q5, Q17)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="quota"
    )
    day = models.DateField()
    used = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "quota"
        # `agentic_backend/` upserts with ON CONFLICT (user_id, day); that statement needs
        # this constraint to exist. A composite primary key would also work,
        # but this keeps an ordinary `id` for the admin.
        unique_together = (("user", "day"),)
