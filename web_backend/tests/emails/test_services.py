"""Rule tests for `emails/services.py`.

The test runner overrides every `MAILERS` alias with the locmem backend,
so tests that need the real aliases set them with `override_settings`:
`default` = `emails.backend.QueueBackend`, `smtp` = `locmem`, and read
`mail.outbox`.
"""

from datetime import timedelta

from django.core import mail
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.db import transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from emails.models import Email
from emails.services import (
    MAX_ATTEMPTS,
    build_message,
    queue_message,
    requeue_emails,
    send_batch,
)

TEST_MAILERS = {
    "default": {"BACKEND": "emails.backend.QueueBackend"},
    "smtp": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"},
}


@override_settings(MAILERS=TEST_MAILERS)
class QueueMessageStoreTest(TestCase):
    def test_queue_message_stores_a_plain_message_with_body_and_no_html(self) -> None:
        # Arrange
        message = EmailMessage(
            subject="plain hello",
            body="world",
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
        )
        # Act
        row = queue_message(message)
        # Assert
        self.assertEqual(row.body, "world")
        self.assertEqual(row.html, "")
        self.assertEqual(row.subject, "plain hello")
        self.assertEqual(row.to, ["reader@example.com"])
        self.assertEqual(row.from_email, "noreply@politicalagent.eu")
        self.assertEqual(row.status, Email.Status.PENDING)

    def test_queue_message_stores_a_plain_plus_html_message_split_across_both_fields(self) -> None:
        # Arrange
        message = EmailMultiAlternatives(
            subject="multipart hello",
            body="world",
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
        )
        message.attach_alternative("<p>world</p>", "text/html")
        # Act
        row = queue_message(message)
        # Assert
        self.assertEqual(row.body, "world")
        self.assertEqual(row.html, "<p>world</p>")

    def test_queue_message_stores_an_html_only_message_into_the_html_field(self) -> None:
        # Arrange
        # allauth builds one of these when only an `.html` template exists.
        message = EmailMessage(
            subject="html-only hello",
            body="<p>world</p>",
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
        )
        message.content_subtype = "html"
        self.assertFalse(message.attachments)
        # Act
        row = queue_message(message)
        # Assert
        self.assertEqual(row.body, "")
        self.assertEqual(row.html, "<p>world</p>")

    def test_queue_message_rejects_a_message_without_recipients(self) -> None:
        # Arrange
        count_before = Email.objects.count()
        message = EmailMessage(
            subject="nobody",
            body="world",
            from_email="noreply@politicalagent.eu",
            to=[],
        )
        # Act
        with self.assertRaises(ValueError) as raised:
            queue_message(message)
        # Assert
        self.assertIn("recipients", str(raised.exception))
        self.assertEqual(Email.objects.count(), count_before)

    def test_queue_message_rejects_an_attachment_and_makes_no_row(self) -> None:
        # Arrange
        count_before = Email.objects.count()
        message = EmailMessage(
            subject="no attachments",
            body="world",
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
        )
        message.attach("invoice.txt", "pdf", "text/plain")
        # Act
        with self.assertRaises(ValueError) as raised:
            queue_message(message)
        # Assert
        self.assertIn("attachments", str(raised.exception))
        self.assertEqual(Email.objects.count(), count_before)

    def test_queue_message_rejects_an_extra_header_and_makes_no_row(self) -> None:
        # Arrange
        count_before = Email.objects.count()
        message = EmailMessage(
            subject="no extra headers",
            body="world",
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
        )
        message.extra_headers = {"X-My-Header": "x"}
        # Act
        with self.assertRaises(ValueError) as raised:
            queue_message(message)
        # Assert
        self.assertIn("X-My-Header", str(raised.exception))
        self.assertEqual(Email.objects.count(), count_before)

    def test_queue_message_rejects_a_non_html_alternative_and_makes_no_row(self) -> None:
        # Arrange
        count_before = Email.objects.count()
        message = EmailMultiAlternatives(
            subject="no other alternatives",
            body="world",
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
        )
        message.attach_alternative("raw:bytes", "image/png")
        # Act
        with self.assertRaises(ValueError) as raised:
            queue_message(message)
        # Assert
        self.assertIn("image/png", str(raised.exception))
        self.assertEqual(Email.objects.count(), count_before)


@override_settings(MAILERS=TEST_MAILERS)
class BuildMessageRoundTripTest(TestCase):
    def test_build_message_round_trips_body_and_recipients_unchanged(self) -> None:
        # Arrange
        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="hello",
            body="world",
        )
        # Act
        message = build_message(row)
        # Assert
        self.assertEqual(message.to, ["reader@example.com"])
        self.assertEqual(message.subject, "hello")
        self.assertTrue(message.body.startswith("world"))

    def test_build_message_round_trips_an_html_only_row_through_the_subtype(self) -> None:
        # Arrange
        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="hello",
            html="<p>world</p>",
        )
        # Act
        message = build_message(row)
        # Assert
        self.assertEqual(message.content_subtype, "html")
        self.assertEqual(message.body, "<p>world</p>")

    def test_build_message_sends_a_row_with_body_and_html_as_multipart(self) -> None:
        # Arrange
        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="hello",
            body="world",
            html="<p>world</p>",
        )
        # Act
        message = build_message(row)
        # Assert
        self.assertEqual(message.body, "world")
        self.assertEqual(
            message.alternatives, [("<p>world</p>", "text/html")]
        )

    def test_build_message_round_trips_cc_bcc_and_reply_to(self) -> None:
        # Arrange
        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            cc=["carbon@example.com"],
            bcc=["blind@example.com"],
            reply_to=["replies@example.com"],
            subject="hello",
            body="world",
        )
        # Act
        message = build_message(row)
        # Assert
        self.assertEqual(message.cc, ["carbon@example.com"])
        self.assertEqual(message.bcc, ["blind@example.com"])
        self.assertEqual(message.reply_to, ["replies@example.com"])

    def test_the_queue_and_batch_round_trip_cc_bcc_and_reply_to(self) -> None:
        # Arrange
        message = EmailMultiAlternatives(
            subject="carbon copy",
            body="world",
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            cc=["carbon@example.com"],
            bcc=["blind@example.com"],
            reply_to=["replies@example.com"],
        )
        queue_message(message)
        # Act
        sent, pending = send_batch()
        # Assert
        self.assertEqual((sent, pending), (1, 0))
        sent_message = mail.outbox[0]
        self.assertEqual(sent_message.cc, ["carbon@example.com"])
        self.assertEqual(sent_message.bcc, ["blind@example.com"])
        self.assertEqual(sent_message.reply_to, ["replies@example.com"])


@override_settings(MAILERS=TEST_MAILERS)
class SendBatchSendsTest(TestCase):
    def test_send_batch_sends_a_pending_row_through_the_smtp_alias(self) -> None:
        # Arrange
        message = EmailMessage(
            subject="queued hello",
            body="world",
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
        )
        queue_message(message)
        # Act
        sent, pending = send_batch()
        # Assert
        self.assertEqual(sent, 1)
        self.assertEqual(pending, 0)
        row = Email.objects.get()
        self.assertEqual(row.status, Email.Status.SENT)
        self.assertIsNotNone(row.sent_at)
        self.assertEqual(row.attempts, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "queued hello")
        self.assertEqual(mail.outbox[0].to, ["reader@example.com"])
        self.assertEqual(mail.outbox[0].body, "world")


@override_settings(MAILERS=TEST_MAILERS)
class SendBatchRetriesTest(TestCase):
    def test_a_send_error_adds_an_attempt_and_keeps_the_row_pending(self) -> None:
        # Arrange
        from unittest.mock import patch

        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="will fail",
        )
        # Act
        with patch(
            "django.core.mail.backends.locmem.EmailBackend.send_messages",
            side_effect=Exception("SMTP refused"),
        ):
            sent, pending = send_batch()
        # Assert
        self.assertEqual((sent, pending), (0, 1))
        row.refresh_from_db()
        self.assertEqual(row.status, Email.Status.PENDING)
        self.assertEqual(row.attempts, 1)
        self.assertIn("SMTP refused", row.last_error)

    def test_send_batch_marks_row_failed_after_third_error(self) -> None:
        # Arrange
        from unittest.mock import patch

        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="three failures",
            attempts=2,
        )
        # Act
        with patch("django.core.mail.backends.locmem.EmailBackend.send_messages", side_effect=Exception("SMTP refused")):
            sent, pending = send_batch()
        # Assert
        self.assertEqual((sent, pending), (0, 0))
        row.refresh_from_db()
        self.assertEqual(row.status, Email.Status.FAILED)
        self.assertEqual(row.attempts, MAX_ATTEMPTS)

    def test_a_row_whose_last_attempt_is_two_minutes_ago_is_skipped(self) -> None:
        # Arrange
        from unittest.mock import patch

        started = timezone.now() - timedelta(minutes=2)
        Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="recent retry",
            attempts=1,
            last_attempt_at=started,
        )
        # Act
        with patch("django.core.mail.backends.locmem.EmailBackend.send_messages"):
            sent, pending = send_batch()
        # Assert
        self.assertEqual(sent, 0)
        self.assertEqual(pending, 1)

    def test_a_row_whose_last_attempt_is_six_minutes_ago_is_sent(self) -> None:
        # Arrange
        started = timezone.now() - timedelta(minutes=6)
        Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="old retry",
            attempts=1,
            last_attempt_at=started,
        )
        # Act
        sent, pending = send_batch()
        # Assert
        self.assertEqual(sent, 1)
        self.assertEqual(pending, 0)


@override_settings(MAILERS=TEST_MAILERS)
class SendBatchSliceAndCapTest(TestCase):
    def test_send_batch_sends_a_twenty_row_slice_from_twenty_five_pending(self) -> None:
        # Arrange
        for i in range(25):
            Email.objects.create(
                from_email="noreply@politicalagent.eu",
                to=[f"reader{i}@example.com"],
                subject=f"slice {i}",
            )
        # Act
        sent, pending = send_batch()
        # Assert
        self.assertEqual(sent, 20)
        self.assertEqual(pending, 5)

    def test_the_hourly_cap_limits_the_slice_to_the_remaining_room(self) -> None:
        # Arrange
        from unittest.mock import patch

        now = timezone.now()
        for i in range(3):
            Email.objects.create(
                from_email="noreply@politicalagent.eu",
                to=[f"sent{i}@example.com"],
                subject=f"sent {i}",
                status=Email.Status.SENT,
                sent_at=now - timedelta(minutes=10 * i),
            )
        for i in range(5):
            Email.objects.create(
                from_email="noreply@politicalagent.eu",
                to=[f"pending{i}@example.com"],
                subject=f"pending {i}",
            )
        # Act
        with override_settings(EMAIL_MAX_PER_HOUR=5):
            sent, pending = send_batch()
        # Assert
        self.assertEqual(sent, 2)
        self.assertEqual(pending, 3)

    def test_a_reached_hourly_cap_sends_none_and_reports_the_pending_count(self) -> None:
        # Arrange
        from unittest.mock import patch

        now = timezone.now()
        for i in range(5):
            Email.objects.create(
                from_email="noreply@politicalagent.eu",
                to=[f"sent{i}@example.com"],
                subject=f"sent {i}",
                status=Email.Status.SENT,
                sent_at=now - timedelta(minutes=5),
            )
        for i in range(4):
            Email.objects.create(
                from_email="noreply@politicalagent.eu",
                to=[f"pending{i}@example.com"],
                subject=f"pending {i}",
            )
        # Act
        with override_settings(EMAIL_MAX_PER_HOUR=5):
            with patch("django.core.mail.backends.locmem.EmailBackend.send_messages") as sender:
                sent, pending = send_batch()
        # Assert
        self.assertEqual((sent, pending), (0, 4))
        sender.assert_not_called()


@override_settings(MAILERS=TEST_MAILERS)
class RequeueEmailsTest(TestCase):
    def test_requeue_emails_resets_attempts_and_bumps_resend_count(self) -> None:
        # Arrange
        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="resend me",
            status=Email.Status.SENT,
            attempts=1,
            sent_at=timezone.now(),
            last_error="",
        )
        row.refresh_from_db()
        sent_at_before = row.sent_at
        # Act
        count = requeue_emails(Email.objects.filter(status=Email.Status.SENT))
        row.refresh_from_db()
        # Assert
        self.assertEqual(count, 1)
        self.assertEqual(row.status, Email.Status.PENDING)
        self.assertEqual(row.attempts, 0)
        self.assertEqual(row.resend_count, 1)
        self.assertEqual(row.sent_at, sent_at_before)
        self.assertEqual(row.last_error, "")

    def test_requeue_emails_also_works_on_failed_rows(self) -> None:
        # Arrange
        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="failed resend",
            status=Email.Status.FAILED,
            attempts=3,
            last_error="SMTP refused",
        )
        row.refresh_from_db()
        last_error_before = row.last_error
        # Act
        count = requeue_emails(Email.objects.filter(status=Email.Status.FAILED))
        row.refresh_from_db()
        # Assert
        self.assertEqual(count, 1)
        self.assertEqual(row.status, Email.Status.PENDING)
        self.assertEqual(row.attempts, 0)
        self.assertEqual(row.resend_count, 1)
        self.assertEqual(row.last_error, last_error_before)

    def test_requeue_emails_leaves_pending_rows_untouched(self) -> None:
        # Arrange
        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="already pending",
        )
        # Act
        count = requeue_emails(Email.objects.filter(pk=row.pk))
        row.refresh_from_db()
        # Assert
        self.assertEqual(count, 0)
        self.assertEqual(row.status, Email.Status.PENDING)
        self.assertEqual(row.attempts, 0)
        self.assertEqual(row.resend_count, 0)


class SendBatchSkipsLockedRowTest(TransactionTestCase):
    """The `skip_locked` decision: another process's batch does not stall.

    Postgres only; `skip_locked` is silently ignored by the sqlite test
    fallback. This suite already requires the dev Postgres, so one
    explicit TransactionTestCase keeps the claim honest.
    """

    def test_a_row_locked_by_another_connection_is_skipped_not_stalled(self) -> None:
        # Arrange
        # The lock must sit on a DIFFERENT database connection than
        # `send_batch`'s, or `skip_locked` never sees a conflict: one
        # transaction never blocks itself. A second ConnectionHandler
        # instance gives this test its own connection, and a thread runs
        # the batch on yet another (its process's thread-local one).
        from threading import Thread

        from django.db import connections
        from django.db.utils import ConnectionHandler

        row_1 = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["locked@example.com"],
            subject="locked row",
        )
        row_2 = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["free@example.com"],
            subject="free row",
        )
        handler = ConnectionHandler(settings=connections.settings)
        lock_connection = handler["default"]
        result: dict[str, tuple[int, int] | Exception] = {}

        def run_batch() -> None:
            try:
                result["batch"] = send_batch()
            except Exception as exc:  # pragma: no cover - surfaced below
                result["error"] = exc
            finally:
                connections["default"].close()

        try:
            # Act
            # Open an explicit transaction on the second connection and
            # hold row 1's FOR UPDATE lock while the thread's batch runs.
            # The thread start/join below IS the action under test.
            lock_connection.set_autocommit(False)
            cursor = lock_connection.cursor()
            cursor.execute(
                "SELECT id FROM emails_email WHERE id = %s FOR UPDATE",
                [row_1.pk],
            )
            cursor.fetchone()
            sender = Thread(target=run_batch)
            sender.start()
            sender.join(timeout=10)
            self.assertFalse(
                sender.is_alive(), "send_batch stalled on the locked row"
            )
            lock_connection.rollback()
        finally:
            lock_connection.close()

        # Assert
        if isinstance(result.get("error"), Exception):
            raise result["error"]  # type: ignore[misc]
        sent, pending = result["batch"]  # type: ignore[misc]
        self.assertEqual(sent, 1)
        self.assertEqual(pending, 1)
        row_1.refresh_from_db()
        row_2.refresh_from_db()
        self.assertEqual(row_1.status, Email.Status.PENDING)
        self.assertEqual(row_2.status, Email.Status.SENT)


@override_settings(MAILERS=TEST_MAILERS)
class SendBatchMailerConnectionFailureTest(TestCase):
    """open()/QUIT failures abort the batch after the claim; rows retry."""

    def test_an_smtp_open_failure_preserves_the_claimed_attempts(self) -> None:
        # Arrange
        from unittest.mock import patch

        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="open refused",
        )
        # Act
        with patch(
            "django.core.mail.backends.locmem.EmailBackend.open",
            side_effect=Exception("SMTP open refused"),
        ):
            sent, pending = send_batch()
        # Assert
        self.assertEqual(sent, 0)
        self.assertEqual(pending, 1)
        row.refresh_from_db()
        self.assertEqual(row.status, Email.Status.PENDING)
        self.assertEqual(row.attempts, 1)
        self.assertIsNotNone(row.last_attempt_at)

    def test_a_smtp_close_failure_after_a_send_keeps_the_sent_rows_sent(self) -> None:
        # Arrange
        from unittest.mock import patch

        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="close refused",
        )
        # Act
        with patch(
            "django.core.mail.backends.locmem.EmailBackend.close",
            side_effect=Exception("SMTP close refused"),
        ):
            sent, pending = send_batch()
        # Assert
        self.assertEqual(sent, 1)
        self.assertEqual(pending, 0)
        row.refresh_from_db()
        self.assertEqual(row.status, Email.Status.SENT)
        self.assertEqual(len(mail.outbox), 1)


@override_settings(MAILERS=TEST_MAILERS)
class SendBatchMixedBatchTest(TestCase):
    def test_one_failing_row_among_others_fails_alone(self) -> None:
        # Arrange
        from unittest.mock import patch

        failing = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["first@example.com"],
            subject="fails",
        )
        keep = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["second@example.com"],
            subject="sends",
        )
        also_keep = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["third@example.com"],
            subject="sends too",
        )
        # Act
        with patch(
            "django.core.mail.backends.locmem.EmailBackend.send_messages",
            side_effect=[Exception("boom"), 1, 1],
        ):
            sent, pending = send_batch()
        # Assert
        self.assertEqual((sent, pending), (2, 1))
        failing.refresh_from_db()
        keep.refresh_from_db()
        also_keep.refresh_from_db()
        self.assertEqual(failing.status, Email.Status.PENDING)
        self.assertIn("boom", failing.last_error)
        self.assertEqual(failing.attempts, 1)
        self.assertEqual(keep.status, Email.Status.SENT)
        self.assertEqual(also_keep.status, Email.Status.SENT)

    def test_a_send_error_longer_than_the_last_error_column_is_truncated(self) -> None:
        # Arrange
        from unittest.mock import patch

        row = Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="long error",
        )
        # Act
        with patch(
            "django.core.mail.backends.locmem.EmailBackend.send_messages",
            side_effect=Exception("x" * 5000),
        ):
            sent, pending = send_batch()
        # Assert
        self.assertEqual(sent, 0)
        row.refresh_from_db()
        self.assertEqual(len(row.last_error), 2000)
        self.assertEqual(pending, 1)


@override_settings(MAILERS=TEST_MAILERS)
class SendBatchBoundaryTest(TestCase):
    """The exact RETRY_WAIT, CAP_WINDOW and MAX_ATTEMPTS edges."""

    def setUp(self) -> None:
        self.clock = timezone.now()

    def test_a_row_whose_last_attempt_is_exactly_the_retry_wait_ago_is_sent(self) -> None:
        # Arrange
        from unittest.mock import patch

        Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="on the edge",
            attempts=1,
            last_attempt_at=self.clock - timedelta(minutes=5),
        )
        # Act
        with patch("emails.services.timezone.now", return_value=self.clock):
            sent, pending = send_batch()
        # Assert
        self.assertEqual(sent, 1)
        self.assertEqual(pending, 0)

    def test_a_sent_row_exactly_the_cap_window_old_is_not_counted_against_the_cap(self) -> None:
        # Arrange
        from unittest.mock import patch

        for i in range(5):
            Email.objects.create(
                from_email="noreply@politicalagent.eu",
                to=[f"sent{i}@example.com"],
                subject=f"sent {i}",
                status=Email.Status.SENT,
                sent_at=self.clock - timedelta(hours=1),
            )
        for i in range(6):
            Email.objects.create(
                from_email="noreply@politicalagent.eu",
                to=[f"pending{i}@example.com"],
                subject=f"pending {i}",
            )
        # Act
        with patch("emails.services.timezone.now", return_value=self.clock):
            with override_settings(EMAIL_MAX_PER_HOUR=5):
                sent, pending = send_batch()
        # Assert
        self.assertEqual(sent, 5)
        self.assertEqual(pending, 1)

    def test_a_pending_row_at_the_max_attempts_edge_is_never_claimed(self) -> None:
        # Arrange
        from unittest.mock import patch

        Email.objects.create(
            from_email="noreply@politicalagent.eu",
            to=["reader@example.com"],
            subject="exhausted",
            attempts=3,
        )
        # Act
        with patch("emails.services.timezone.now", return_value=self.clock):
            sent, pending = send_batch()
        # Assert
        self.assertEqual(sent, 0)
        self.assertEqual(pending, 1)
