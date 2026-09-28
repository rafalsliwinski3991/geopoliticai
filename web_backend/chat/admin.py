"""Admin for the Django-owned chat_threads, quota, and site_quota tables."""

from django.contrib import admin, messages

from chat.management.commands.purge_prelaunch_threads import orphan_thread_ids
from chat.models import Quota, SiteQuota, Thread

CHECKPOINTER_TABLES_MISSING = (
    "The checkpointer tables are missing; run the checkpointer's setup() first."
)


@admin.register(Thread)
class ThreadAdmin(admin.ModelAdmin):
    """Thread admin: the id is the conversation key the chat UI stores."""

    list_display = ("id", "title", "user", "created_at")
    search_fields = ("id", "title", "user__email")
    raw_id_fields = ("user",)
    actions = ("check_orphaned_threads",)

    @admin.display(description="Check for orphaned checkpointer threads")
    @admin.action(description="Check for orphaned checkpointer threads")
    def check_orphaned_threads(self, request, queryset) -> None:
        orphans = orphan_thread_ids()
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

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(SiteQuota)
class SiteQuotaAdmin(admin.ModelAdmin):
    """Read-only: the site counter is written by the API's own SQL, never by hand."""

    list_display = ("day", "used")
    readonly_fields = ("day", "used")

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
