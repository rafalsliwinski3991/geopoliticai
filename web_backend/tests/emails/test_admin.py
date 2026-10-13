from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from emails.models import Email

User = get_user_model()

TEST_MAILERS = {
    "default": {"BACKEND": "emails.backend.QueueBackend"},
    "smtp": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"},
}


def make_row(subject: str, to: str = "reader@example.com") -> Email:
    return Email.objects.create(
        from_email="noreply@politicalagent.eu",
        to=[to],
        subject=subject,
    )


@override_settings(MAILERS=TEST_MAILERS)
class EmailAdminPermissionTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.superuser = User.objects.create_superuser(
            email="boss@example.com", password="resolute-amber-8"
        )
        cls.row = make_row("guarded row")

    def setUp(self) -> None:
        self.client.force_login(self.superuser)

    def test_rows_cannot_be_added_by_hand(self) -> None:
        # Arrange
        email_admin = django_admin.site._registry[Email]
        # Act
        allowed = email_admin.has_add_permission(None)
        # Assert
        self.assertFalse(allowed)

    def test_rows_cannot_be_deleted(self) -> None:
        # Arrange
        email_admin = django_admin.site._registry[Email]
        # Act
        allowed = email_admin.has_delete_permission(None)
        # Assert
        self.assertFalse(allowed)

    def test_the_changelist_searches_the_json_to_column(self) -> None:
        # Arrange
        make_row("searchable subject", to="needle@example.com")
        url = reverse("admin:emails_email_changelist")
        # Act
        response = self.client.get(url, {"q": "needle@example.com"})
        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "searchable subject")
        self.assertNotContains(response, "guarded row")


@override_settings(MAILERS=TEST_MAILERS)
class EmailAdminResendActionTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.superuser = User.objects.create_superuser(
            email="boss@example.com", password="resolute-amber-8"
        )

    def setUp(self) -> None:
        self.client.force_login(self.superuser)

    def test_resend_selected_sets_rows_pending_and_reports_it(self) -> None:
        # Arrange
        row = make_row("resend target")
        row.status = Email.Status.FAILED
        row.attempts = 3
        row.save()
        changelist = reverse("admin:emails_email_changelist")
        action_data = {
            "action": "resend_selected",
            "_selected_action": [str(row.pk)],
        }
        # Act
        response = self.client.post(changelist, action_data, follow=True)
        # Assert
        self.assertEqual(response.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.status, Email.Status.PENDING)
        self.assertEqual(row.attempts, 0)
        self.assertEqual(row.resend_count, 1)
        self.assertContains(response, "1 email(s) set to pending.")

    def test_a_staff_user_without_change_permission_is_refused_the_resend_action(self) -> None:
        # Arrange
        # A staff member without the `change` model permission: view-only.
        self.client.force_login(
            User.objects.create_user(
                email="readonly@example.com",
                password="resolute-amber-8",
                is_staff=True,
            )
        )
        row = make_row("sent row")
        row.status = Email.Status.SENT
        row.save()
        changelist = reverse("admin:emails_email_changelist")
        action_data = {
            "action": "resend_selected",
            "_selected_action": [str(row.pk)],
        }
        # Act
        response = self.client.post(changelist, action_data, follow=True)
        # Assert
        row.refresh_from_db()
        self.assertNotEqual(row.status, Email.Status.PENDING)
        self.assertEqual(row.resend_count, 0)


@override_settings(MAILERS=TEST_MAILERS)
class SendPendingNowButtonTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.superuser = User.objects.create_superuser(
            email="boss@example.com", password="resolute-amber-8"
        )
        cls.passerby = User.objects.create_user(
            email="passerby@example.com",
            password="resolute-amber-8",
            is_staff=True,
        )

    def test_a_superuser_post_sends_a_slice_and_redirects_to_the_changelist(self) -> None:
        # Arrange
        self.client.force_login(self.superuser)
        for i in range(2):
            make_row(f"queued {i}")
        url = reverse("admin:emails_email_send_pending_now")
        # Act
        response = self.client.post(url, follow=True)
        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Email.objects.filter(status=Email.Status.SENT).count(), 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertContains(response, "2 sent, 0 still pending.")

    def test_a_get_is_refused_as_method_not_allowed(self) -> None:
        # Arrange
        self.client.force_login(self.superuser)
        url = reverse("admin:emails_email_send_pending_now")
        # Act
        response = self.client.get(url)
        # Assert
        self.assertEqual(response.status_code, 405)

    def test_a_non_staff_user_is_redirected_to_login(self) -> None:
        # Arrange
        url = reverse("admin:emails_email_send_pending_now")
        # Act
        response = self.client.post(url)
        # Assert
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_a_staff_user_without_change_permission_gets_a_403(self) -> None:
        # Arrange
        self.client.force_login(self.passerby)
        make_row("not sent without permission")
        url = reverse("admin:emails_email_send_pending_now")
        # Act
        response = self.client.post(url)
        # Assert
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            Email.objects.filter(status=Email.Status.SENT).count(), 0
        )

    def test_the_changelist_shows_the_pending_count_and_the_oldest_age(self) -> None:
        # Arrange
        self.client.force_login(self.superuser)
        make_row("oldest queued")
        make_row("newest queued")
        url = reverse("admin:emails_email_changelist")
        # Act
        response = self.client.get(url)
        # Assert
        self.assertEqual(response.context["pending_count"], 2)
        self.assertTrue(response.context["oldest_pending_age"])
        self.assertContains(response, "Send pending now")
        self.assertContains(response, "2 pending")
