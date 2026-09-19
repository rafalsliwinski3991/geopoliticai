"""Tests for the Django-owned chat_threads and quota models (unit 4)."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from chat.models import Quota

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
