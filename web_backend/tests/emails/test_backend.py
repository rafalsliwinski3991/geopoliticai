"""The queue as Django's `MAILERS["default"]`: `mail.send_mail` queues,
allauth's signup confirmation and password reset queue, and nothing is
sent until `send_batch` runs.
"""

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

SIGNUP_PASSWORD = "resolute-amber-8"


@override_settings(MAILERS=TEST_MAILERS)
class SendMailQueuesTest(TestCase):
    def test_send_mail_creates_one_pending_row_and_sends_nothing(self) -> None:
        # Arrange
        # Act
        count = mail.send_mail(
            subject="direct hello",
            message="world",
            from_email="noreply@politicalagent.eu",
            recipient_list=["reader@example.com"],
        )
        # Assert
        self.assertEqual(count, 1)
        row = Email.objects.get()
        self.assertEqual(row.status, Email.Status.PENDING)
        self.assertEqual(row.subject, "direct hello")
        self.assertEqual(row.to, ["reader@example.com"])
        self.assertEqual(len(mail.outbox), 0)


@override_settings(MAILERS=TEST_MAILERS)
class AllauthMailQueuesTest(TestCase):
    def test_a_real_signup_queues_the_confirmation_mail_with_its_link(self) -> None:
        # Arrange
        # Act
        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "patient@example.com",
                "password1": SIGNUP_PASSWORD,
                "password2": SIGNUP_PASSWORD,
            },
        )
        # Assert
        self.assertEqual(response.status_code, 302)
        row = Email.objects.get()
        self.assertEqual(row.status, Email.Status.PENDING)
        storing = row.body or row.html
        self.assertIn("confirm-email", storing)
        self.assertIn("patient@example.com", row.to)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_real_password_reset_request_queues_the_reset_mail_with_its_link(self) -> None:
        # Arrange
        User.objects.create_user(
            email="resevoir@example.com", password=SIGNUP_PASSWORD
        )
        # allauth's reset flow only mails for an existing address, and the
        # address has to be verified for the reset view to continue.
        user = User.objects.get(email="resevoir@example.com")
        from allauth.account.models import EmailAddress

        EmailAddress.objects.create(
            user=user, email=user.email, verified=True, primary=True
        )
        # Act
        response = self.client.post(
            reverse("account_reset_password"),
            {"email": "resevoir@example.com"},
        )
        # Assert
        self.assertEqual(response.status_code, 302)
        row = Email.objects.get()
        self.assertEqual(row.status, Email.Status.PENDING)
        storing = row.body or row.html
        self.assertIn("reset/key/", storing)
        self.assertIn("resevoir@example.com", row.to)
        self.assertEqual(len(mail.outbox), 0)
