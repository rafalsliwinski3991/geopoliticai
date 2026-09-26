"""Tests for the Django-owned chat_threads and quota models (unit 4)."""

import importlib
from datetime import date
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from chat.models import Quota, SiteQuota

User = get_user_model()


class ThreadModelTest(TestCase):
    """The chat_threads round-trip: one conversation, owned by one user."""

    def test_thread_round_trip_and_str(self) -> None:
        # Arrange
        user = User.objects.create_user(email="r@example.com", password="x-not-used-1")

        # Act
        user.threads.create(id="abc123", title="Question about NATO")
        fetched = user.threads.get(id="abc123")

        # Assert
        self.assertEqual(str(fetched), "Question about NATO")

    def test_thread_str_falls_back_to_the_id(self) -> None:
        # Arrange
        user = User.objects.create_user(email="r2@example.com", password="x-not-used-1")

        # Act
        thread = user.threads.create(id="plain-id")

        # Assert
        self.assertEqual(str(thread), "plain-id")


class QuotaModelTest(TestCase):
    """The quota round-trip and its (user, day) uniqueness."""

    def test_quota_round_trip(self) -> None:
        # Arrange
        user = User.objects.create_user(email="q@example.com", password="x-not-used-1")

        # Act
        Quota.objects.create(user=user, day=date(2026, 9, 18), used=3)

        # Assert
        self.assertEqual(user.quota.get(day=date(2026, 9, 18)).used, 3)


class SiteQuotaModelTest(TestCase):
    """The site-wide counter: one row per UTC day, copied from the sentinel."""

    def test_one_row_per_day(self) -> None:
        # Arrange
        SiteQuota.objects.create(day=date(2026, 9, 18), used=1)

        # Act / Assert
        with self.assertRaises(IntegrityError), transaction.atomic():
            SiteQuota.objects.create(day=date(2026, 9, 18), used=2)

    def test_copy_migration_moves_the_sentinel_rows(self) -> None:
        # Arrange: unit 4 deletes the sentinel, so create it when absent.
        User.objects.get_or_create(
            id=0, defaults={"email": "sentinel@test.invalid", "is_active": False}
        )
        first, second = date(2026, 9, 17), date(2026, 9, 18)
        Quota.objects.create(user_id=0, day=first, used=7)
        Quota.objects.create(user_id=0, day=second, used=2)
        migration = importlib.import_module("chat.migrations.0004_copy_site_quota")

        # Act
        migration.copy_sentinel_rows(None, SimpleNamespace(connection=connection))

        # Assert
        self.assertEqual(
            dict(SiteQuota.objects.values_list("day", "used")), {first: 7, second: 2}
        )
        self.assertEqual(Quota.objects.filter(user_id=0).count(), 2)
