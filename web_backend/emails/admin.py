from django import http
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.defaultfilters import timesince
from django.urls import path
from django.utils import timezone

from emails.models import Email
from emails.services import requeue_emails, send_batch


@admin.register(Email)
class EmailAdmin(admin.ModelAdmin):
    list_display = ("created_at", "to_display", "subject", "status", "attempts", "sent_at")
    list_filter = ("status",)
    search_fields = ("subject", "to")
    readonly_fields = [field.name for field in Email._meta.fields]
    actions = ("resend_selected",)
    list_display_links = ("subject",)

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False

    @admin.action(description="Resend selected", permissions=["change"])
    def resend_selected(self, request, queryset) -> None:
        count = requeue_emails(queryset)
        self.message_user(
            request, f"{count} email(s) set to pending.", messages.SUCCESS
        )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "send-pending-now/",
                self.admin_site.admin_view(self.send_pending_now),
                name="emails_email_send_pending_now",
            ),
        ]
        return custom + urls

    def send_pending_now(self, request):
        if request.method != "POST":
            return http.HttpResponseNotAllowed(["POST"])
        if not self.has_change_permission(request):
            raise PermissionDenied
        sent, pending = send_batch()
        self.message_user(
            request, f"{sent} sent, {pending} still pending.", messages.SUCCESS
        )
        return redirect("admin:emails_email_changelist")

    def changelist_view(self, request, extra_context=None):
        pending = Email.objects.filter(status=Email.Status.PENDING)
        oldest = pending.order_by("created_at").first()
        extra_context = extra_context or {}
        extra_context["pending_count"] = pending.count()
        extra_context["oldest_pending_age"] = (
            timesince(oldest.created_at, timezone.now()) if oldest else None
        )
        return super().changelist_view(request, extra_context)

    @admin.display(description="To")
    def to_display(self, obj):
        return ", ".join(obj.to)
