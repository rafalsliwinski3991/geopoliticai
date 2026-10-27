"""Admin registration for the email-only user model."""

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone

from chat.services import reset_quota

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Django's UserAdmin adapted to a model with no username field."""

    list_display = ("email", "is_staff", "is_active")
    search_fields = ("email",)
    ordering = ("email",)
    actions = ("reset_todays_quota",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )

    @admin.action(description="Reset today's research quota", permissions=["change"])
    def reset_todays_quota(self, request, queryset) -> None:
        given_back = reset_quota(queryset, timezone.now().date())
        messages.success(
            request,
            f"Gave back {given_back} research unit(s) to {queryset.count()} user(s).",
        )
