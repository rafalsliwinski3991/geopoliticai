from django.db import IntegrityError
from django.test import TestCase

from emails.models import Email


class EmailStatusConstraintTest(TestCase):
    def test_saving_a_row_with_an_unknown_status_raises_integrity_error(self) -> None:
        # Arrange
        # The DB `CheckConstraint` (`emails_email_status_valid`), not a
        # Python-level Choices check: the choice list would raise
        # ValidationError instead. This asserts the row can never sneak a
        # status in through `update()` or raw SQL.
        bogus = Email(
            from_email="noreply@politicalagent.eu",
            to=["someone@example.com"],
            subject="bogus status",
            status="bogus",
        )
        # Act
        with self.assertRaises(IntegrityError) as raised:
            bogus.save()
        # Assert
        self.assertIn("emails_email_status_valid", str(raised.exception))

    def test_a_new_row_defaults_to_pending_with_zero_attempts(self) -> None:
        # Arrange
        # Act
        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["someone@example.com"],
            subject="defaults",
        )
        row.refresh_from_db()
        # Assert
        self.assertEqual(row.status, Email.Status.PENDING)
        self.assertEqual(row.attempts, 0)
        self.assertEqual(row.resend_count, 0)
