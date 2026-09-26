"""Tests for the admin actions over the chat_threads table (unit 4)."""

from datetime import date

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse

from chat.models import SiteQuota

from chat.management.commands.purge_prelaunch_threads import orphan_thread_ids
from chat.signals import CHECKPOINT_SCHEMA

User = get_user_model()


class OrphanQueryTest(TransactionTestCase):
    """The orphan-check SQL runs and reports thread ids absent from chat_threads.

    The checkpointer's `checkpoints` table does not exist in a fresh test
    database, so a minimal stand-in is created for the query-shape test; the
    real table's shape is validated by unit 6's drift test.
    """

    def test_orphan_query_reports_missing_chat_threads(self) -> None:
        # Arrange
        user = User.objects.create_user(email="o@example.com", password="x-not-used-1")
        user.threads.create(id="known")

        # Act
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {CHECKPOINT_SCHEMA}")
            cursor.execute(
                f"CREATE TABLE {CHECKPOINT_SCHEMA}.checkpoints (thread_id TEXT NOT NULL)"
            )
            cursor.execute(
                f"INSERT INTO {CHECKPOINT_SCHEMA}.checkpoints (thread_id) VALUES ('ghost')"
            )
        orphans = orphan_thread_ids()

        # Assert
        self.assertEqual(orphans, ["ghost"])

    def test_missing_checkpointer_table_is_reported_not_raised(self) -> None:
        # Act
        # A test database has no checkpointer tables; the admin action must
        # degrade to a warning, not a 500.
        orphans = orphan_thread_ids()

        # Assert
        self.assertEqual(orphans, None)


class SiteQuotaAdminTest(TestCase):
    """The site counter is visible to staff and never editable by hand."""

    def test_changelist_renders_for_a_superuser(self) -> None:
        # Arrange
        admin_user = User.objects.create_superuser(
            email="root@example.com", password="x-not-used-1"
        )
        SiteQuota.objects.create(day=date(2026, 9, 18), used=4)
        self.client.force_login(admin_user)

        # Act
        response = self.client.get(reverse("admin:chat_sitequota_changelist"))

        # Assert
        self.assertEqual(response.status_code, 200)

    def test_add_change_and_delete_are_denied(self) -> None:
        # Arrange
        model_admin = admin.site._registry[SiteQuota]
        request = RequestFactory().get("/")
        request.user = User.objects.create_superuser(
            email="root2@example.com", password="x-not-used-1"
        )

        # Act / Assert
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
