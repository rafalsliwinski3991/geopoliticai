from datetime import date

from django.test import TestCase

from chat.models import Quota
from chat.services import reset_quota
from users.models import User

RESET_DAY = date(2026, 10, 27)
OTHER_DAY = date(2026, 10, 26)
SPENT_UNITS = 30


class ResetQuotaTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user("a@example.com", "pass-word-1")
        self.other = User.objects.create_user("b@example.com", "pass-word-2")

    def test_reset_quota_sets_the_days_count_to_zero_and_returns_the_units(self):
        """An admin giving a user their day back needs the units they got, to say so."""
        # Arrange
        Quota.objects.create(user=self.user, day=RESET_DAY, used=SPENT_UNITS)

        # Act
        given_back = reset_quota([self.user], RESET_DAY)

        # Assert
        self.assertEqual(given_back, SPENT_UNITS)
        self.assertEqual(Quota.objects.get(user=self.user, day=RESET_DAY).used, 0)

    def test_reset_quota_leaves_the_users_other_days_alone(self):
        """Only the day passed counts toward the cap; other days are history."""
        # Arrange
        Quota.objects.create(user=self.user, day=RESET_DAY, used=SPENT_UNITS)
        Quota.objects.create(user=self.user, day=OTHER_DAY, used=SPENT_UNITS)

        # Act
        reset_quota([self.user], RESET_DAY)

        # Assert
        self.assertEqual(
            Quota.objects.get(user=self.user, day=OTHER_DAY).used, SPENT_UNITS
        )

    def test_reset_quota_leaves_users_it_was_not_given_alone(self):
        """Resetting one user must not hand another user their day back."""
        # Arrange
        Quota.objects.create(user=self.user, day=RESET_DAY, used=SPENT_UNITS)
        Quota.objects.create(user=self.other, day=RESET_DAY, used=SPENT_UNITS)

        # Act
        reset_quota([self.user], RESET_DAY)

        # Assert
        self.assertEqual(
            Quota.objects.get(user=self.other, day=RESET_DAY).used, SPENT_UNITS
        )

    def test_reset_quota_adds_up_the_units_of_several_users(self):
        """The admin selects several users at once and shows one total."""
        # Arrange
        Quota.objects.create(user=self.user, day=RESET_DAY, used=SPENT_UNITS)
        Quota.objects.create(user=self.other, day=RESET_DAY, used=10)

        # Act
        given_back = reset_quota([self.user, self.other], RESET_DAY)

        # Assert
        self.assertEqual(given_back, 40)
        self.assertEqual(Quota.objects.filter(day=RESET_DAY, used=0).count(), 2)

    def test_reset_quota_for_a_user_with_no_row_returns_zero_and_adds_none(self):
        """A user who spent nothing that day has no row; the reset must not invent one."""
        # Arrange
        # setUp creates no quota row for self.user.

        # Act
        given_back = reset_quota([self.user], RESET_DAY)

        # Assert
        self.assertEqual(given_back, 0)
        self.assertFalse(Quota.objects.filter(user=self.user).exists())
