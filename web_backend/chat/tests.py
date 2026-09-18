"""Tests for the Django-owned chat_threads and quota schema (unit 4).

The *deletion cascade* into the checkpointer tables needs those tables to
exist; it is asserted by unit 6's integration suite against a real checkpointer
schema, not here — see the plan's §3 unit 4.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models.signals import pre_delete
from django.test import TestCase, TransactionTestCase

from chat import signals
from chat.admin import orphan_threads_admin_action
from chat.models import Quota

User = get_user_model()


class ThreadModelTest(TestCase):
    """The chat_threads round-trip: one conversation, owned by one user."""

    def test_thread_round_trip_and_str(self) -> None:
        user = User.objects.create_user(email="r@example.com", password="x-not-used-1")
        user.threads.create(id="abc123", title="Question about NATO")
        fetched = user.threads.get(id="abc123")
        self.assertEqual(str(fetched), "Question about NATO")

    def test_thread_str_falls_back_to_the_id(self) -> None:
        user = User.objects.create_user(email="r2@example.com", password="x-not-used-1")
        thread = user.threads.create(id="plain-id")
        self.assertEqual(str(thread), "plain-id")


class QuotaModelTest(TestCase):
    """The quota round-trip and its (user, day) uniqueness."""

    def test_quota_round_trip(self) -> None:
        user = User.objects.create_user(email="q@example.com", password="x-not-used-1")
        quota = Quota.objects.create(user=user, day=date(2026, 9, 18), used=3)
        self.assertEqual(user.quota.get(day=date(2026, 9, 18)).used, 3)


class OrphanQueryTest(TransactionTestCase):
    """The orphan-check SQL runs and reports thread ids absent from chat_threads.

    The checkpointer's `checkpoints` table does not exist in a fresh test
    database, so a minimal stand-in is created for the query-shape test; the
    real table's shape is validated by unit 6's drift test.
    """

    def test_orphan_query_reports_missing_chat_threads(self) -> None:
        user = User.objects.create_user(email="o@example.com", password="x-not-used-1")
        user.threads.create(id="known")
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE checkpoints (thread_id TEXT NOT NULL)")
            cursor.execute("INSERT INTO checkpoints (thread_id) VALUES ('ghost')")
        self.assertEqual(orphan_threads_admin_action(), ["ghost"])

    def test_missing_checkpointer_table_is_reported_not_raised(self) -> None:
        # A test database has no checkpointer tables; the admin action must
        # degrade to a warning, not a 500.
        self.assertEqual(orphan_threads_admin_action(), None)


class DeleteSignalTest(TestCase):
    """The pre_delete receiver is registered against the project's user model."""

    def test_receiver_is_connected(self) -> None:
        # A missing ChatConfig.ready() import fails nothing else: models pass,
        # migrations apply, and the data quietly survives the delete.
        sync_receivers, _ = pre_delete._live_receivers(User)
        self.assertIn(signals.delete_checkpointed_messages, sync_receivers)
