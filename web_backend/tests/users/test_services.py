from allauth.account.models import EmailAddress
from django.test import TestCase
from django.utils import timezone

from chat.models import Quota
from users.models import User
from users.services import ensure_e2e_user


class EnsureE2eUserTests(TestCase):
    def test_ensure_e2e_user_creates_a_user_with_a_verified_primary_email(self):
        # Arrange
        email, password = "e2e@example.com", "s3cret-pass-1"

        # Act
        user = ensure_e2e_user(email, password)

        # Assert
        self.assertTrue(User.objects.get(email=email).check_password(password))
        self.assertEqual(user.email, email)
        addresses = EmailAddress.objects.filter(user=user)
        self.assertEqual(addresses.count(), 1)
        self.assertTrue(addresses.get().verified)
        self.assertTrue(addresses.get().primary)

    def test_ensure_e2e_user_twice_keeps_one_user_and_resets_the_password(self):
        # Arrange
        ensure_e2e_user("e2e@example.com", "old-pass-123")

        # Act
        user = ensure_e2e_user("e2e@example.com", "new-pass-456")

        # Assert
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(EmailAddress.objects.count(), 1)
        user.refresh_from_db()
        self.assertTrue(user.check_password("new-pass-456"))
        self.assertFalse(user.check_password("old-pass-123"))

    def test_ensure_e2e_user_lowercases_the_email(self):
        # Arrange
        email = "E2E@Example.COM"

        # Act
        user = ensure_e2e_user(email, "s3cret-pass-1")

        # Assert
        self.assertEqual(user.email, "e2e@example.com")
        self.assertEqual(EmailAddress.objects.get().email, "e2e@example.com")

    def test_ensure_e2e_user_refills_the_quota(self):
        # Arrange
        user = ensure_e2e_user("e2e@example.com", "s3cret-pass-1")
        Quota.objects.create(user=user, day=timezone.now().date(), used=20)

        # Act
        ensure_e2e_user("e2e@example.com", "s3cret-pass-1")

        # Assert
        self.assertFalse(Quota.objects.filter(user=user).exists())
