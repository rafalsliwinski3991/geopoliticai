from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from emails.models import Email

TEST_MAILERS = {
    "default": {"BACKEND": "emails.backend.QueueBackend"},
    "smtp": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"},
}


@override_settings(MAILERS=TEST_MAILERS)
class SendQueuedEmailsCommandTest(TestCase):
    def test_two_pending_rows_are_sent_and_the_output_reports_the_counts(self) -> None:
        # Arrange
        Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["one@example.com"],
            subject="first",
        )
        Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["two@example.com"],
            subject="second",
        )
        stdout = StringIO()
        # Act
        call_command("send_queued_emails", stdout=stdout)
        # Assert
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(Email.objects.filter(status=Email.Status.SENT).count(), 2)
        self.assertEqual(
            stdout.getvalue().strip(), "sent 2, pending 0"
        )
