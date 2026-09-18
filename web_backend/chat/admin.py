"""Admin for the Django-owned chat_threads and quota tables."""

from django.contrib import admin, messages
from django.db import connection
from django.db.utils import ProgrammingError
from django.utils.html import format_html

from chat.models import Quota, Thread

# The orphan-check query the brainstorm specifies verbatim (flag 5). It reads
# the LangGraph checkpointer's tables, which Django owns no migration for —
# they exist because `agentic_backend`'s checkpointer ran its `setup()`.
ORPHAN_THREAD_SQL = """
SELECT DISTINCT thread_id
FROM checkpoints
WHERE thread_id NOT IN (SELECT id FROM chat_threads)
"""


def orphan_threads_admin_action() -> list[str] | None:
    """Return thread ids checkpointed but missing from chat_threads.

    Returns None when the checkpointer tables do not exist yet (a fresh
    database): the action is a safety net, not a cleaner, and must not turn
    the admin into a 500.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(ORPHAN_THREAD_SQL)
            return [row[0] for row in cursor.fetchall()]
    except ProgrammingError:
        return None


CHECKPOINTER_TABLES_MISSING = (
    "The checkpointer tables are missing; run the checkpointer's setup() first."
)


@admin.register(Thread)
class ThreadAdmin(admin.ModelAdmin):
    """Thread admin with a link to the live conversation in the chat UI."""

    list_display = ("id", "title", "user", "created_at", "open_chat_link")
    search_fields = ("id", "title", "user__email")
    raw_id_fields = ("user",)
    actions = ("check_orphaned_threads",)

    @admin.display(description="Live conversation")
    def open_chat_link(self, obj: Thread) -> str:
        return format_html('<a href="/chat">Open chat</a> <code>{}</code>', obj.id)

    @admin.display(description="Check for orphaned checkpointer threads")
    @admin.action(description="Check for orphaned checkpointer threads")
    def check_orphaned_threads(self, request, queryset) -> None:
        orphans = orphan_threads_admin_action()
        if orphans is None:
            messages.warning(request, CHECKPOINTER_TABLES_MISSING)
        else:
            messages.warning(
                request,
                f"{len(orphans)} checkpointed thread id(s) have no chat_threads row.",
            )


@admin.register(Quota)
class QuotaAdmin(admin.ModelAdmin):
    """Read-only: the quota is written by the API's own SQL, never by hand."""

    list_display = ("user", "day", "used")
    list_filter = ("day",)
    search_fields = ("user__email",)
    readonly_fields = ("user", "day", "used")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False
