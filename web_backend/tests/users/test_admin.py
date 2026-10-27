from datetime import UTC, date, datetime
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from chat.models import Quota
from users.models import User

TODAY = date(2026, 10, 27)
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
SPENT_UNITS = 30
RESET_ACTION = "reset_todays_quota"
USER_LIST = "admin:users_user_changelist"


class ResetTodaysQuotaActionTests(TestCase):
    def setUp(self) -> None:
        self.admin_user = User.objects.create_superuser(
            "root@example.com", "pass-word-0"
        )
        self.user = User.objects.create_user("a@example.com", "pass-word-1")
        self.other = User.objects.create_user("b@example.com", "pass-word-2")
        Quota.objects.create(user=self.user, day=TODAY, used=SPENT_UNITS)
        Quota.objects.create(user=self.other, day=TODAY, used=SPENT_UNITS)

    def run_action(self, selected: list[User]):
        with patch("users.admin.timezone") as clock:
            clock.now.return_value = NOW
            return self.client.post(
                reverse(USER_LIST),
                {"action": RESET_ACTION, "_selected_action": [u.pk for u in selected]},
                follow=True,
            )

    def test_the_reset_action_gives_a_selected_users_day_back_and_says_so(self):
        """Support staff reset one user's day from the user list and see what it did."""
        # Arrange
        self.client.force_login(self.admin_user)

        # Act
        response = self.run_action([self.user])

        # Assert
        self.assertEqual(Quota.objects.get(user=self.user, day=TODAY).used, 0)
        shown = [str(message) for message in response.context["messages"]]
        self.assertEqual(shown, ["Gave back 30 research unit(s) to 1 user(s)."])

    def test_the_reset_action_leaves_unselected_users_alone(self):
        """Only the ticked users get their day back."""
        # Arrange
        self.client.force_login(self.admin_user)

        # Act
        self.run_action([self.user])

        # Assert
        self.assertEqual(
            Quota.objects.get(user=self.other, day=TODAY).used, SPENT_UNITS
        )

    def test_a_staff_user_who_cannot_change_users_cannot_run_the_reset(self):
        """The action hands out research units, so it needs the change permission."""
        # Arrange
        viewer = User.objects.create_user(
            "view@example.com", "pass-word-3", is_staff=True
        )
        viewer.user_permissions.add(Permission.objects.get(codename="view_user"))
        self.client.force_login(viewer)

        # Act
        self.run_action([self.user])

        # Assert
        self.assertEqual(Quota.objects.get(user=self.user, day=TODAY).used, SPENT_UNITS)
