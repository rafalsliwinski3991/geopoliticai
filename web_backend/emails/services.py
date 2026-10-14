"""Every rule of the outgoing-mail queue.

`queue_message` stores, `build_message` rebuilds, `send_batch` sends,
`requeue_emails` resends. The admin, the management command and the
mail backend hold no rules and only call these.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core import mail
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.db import connection, models, transaction
from django.utils import timezone

from emails.models import Email

MAX_ATTEMPTS = 3
RETRY_WAIT = timedelta(minutes=5)
SLICE_SIZE = 20
CAP_WINDOW = timedelta(hours=1)
MAILER_ALIAS = "smtp"
LAST_ERROR_MAX_CHARS = 2000
# Postgres advisory-lock key serialising `send_batch` runners against each
# other, so two processes cannot both count the same hourly room.
CAP_LOCK_KEY = 20261013

logger = logging.getLogger(__name__)


def queue_message(message: EmailMessage) -> Email:
    """Store one outgoing message as a `pending` row instead of sending it."""
    if not message.recipients():
        raise ValueError("queued mail cannot be without recipients")
    if message.attachments:
        raise ValueError("queued mail cannot carry attachments")
    if message.extra_headers:
        raise ValueError(
            "queued mail cannot carry extra headers: "
            + ", ".join(sorted(message.extra_headers))
        )
    alternatives = getattr(message, "alternatives", [])
    non_html = [
        (content, mimetype) for content, mimetype in alternatives
        if mimetype != "text/html"
    ]
    if non_html:
        raise ValueError(
            "queued mail can only carry text/html alternatives, not "
            + non_html[0][1]
        )
    html = next(
        (
            content
            for content, mimetype in alternatives
            if mimetype == "text/html"
        ),
        "",
    )
    if message.content_subtype == "html":
        body, html = "", message.body
    else:
        body = message.body
    return Email.objects.create(
        from_email=message.from_email,
        to=list(message.to),
        cc=list(message.cc),
        bcc=list(message.bcc),
        reply_to=list(message.reply_to),
        subject=message.subject,
        body=body,
        html=html,
    )


def build_message(email: Email) -> EmailMessage:
    """Rebuild the Django message a queued row stands for."""
    if email.body:
        message = EmailMultiAlternatives(
            subject=email.subject,
            body=email.body,
            from_email=email.from_email,
            to=email.to,
            cc=email.cc,
            bcc=email.bcc,
            reply_to=email.reply_to,
        )
        if email.html:
            message.attach_alternative(email.html, "text/html")
        return message
    message = EmailMessage(
        subject=email.subject,
        body=email.html,
        from_email=email.from_email,
        to=email.to,
        cc=email.cc,
        bcc=email.bcc,
        reply_to=email.reply_to,
    )
    message.content_subtype = "html"
    return message


def send_batch() -> tuple[int, int]:
    """Send one slice of `pending` rows through the `smtp` mailer.

    Returns `(sent_now, still_pending)`. A row waits at least `RETRY_WAIT`
    after its last attempt, the mail sent in the last `CAP_WINDOW` never
    exceeds `settings.EMAIL_MAX_PER_HOUR`, and rows another process already
    holds locks on are skipped, not waited for.

    The SMTP session runs OUTSIDE the transaction: one short atomic block
    claims the slice (each attempt consumed, `last_attempt_at` stamped,
    which also hides rows mid-send from other runners for `RETRY_WAIT`),
    then every send outcome is saved in its own autocommit save. A crash
    mid-batch therefore cannot lose an attempt or resend delivered mail,
    and a failing QUIT cannot roll back already-sent rows.
    """
    rows = _claim_rows(timezone.now())
    if not rows:
        return 0, _pending_count()
    sent_now = _send_rows(rows)
    return sent_now, _pending_count()


def _claim_rows(now) -> list[Email]:
    """Claim one slice of `pending` rows under the hourly cap.

    Each claimed row has an attempt consumed while it is locked, which also
    hides it mid-send from other runners for `RETRY_WAIT`. Rows another
    process already holds locks on are skipped, not waited for.
    """
    rows: list[Email] = []
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s)", [CAP_LOCK_KEY]
                )
        sent_in_window = Email.objects.filter(sent_at__gt=now - CAP_WINDOW).count()
        room = min(SLICE_SIZE, settings.EMAIL_MAX_PER_HOUR - sent_in_window)
        if room > 0:
            claimable = (
                Email.objects.filter(
                    status=Email.Status.PENDING,
                    attempts__lt=MAX_ATTEMPTS,
                )
                .filter(
                    models.Q(last_attempt_at__isnull=True)
                    | models.Q(last_attempt_at__lte=now - RETRY_WAIT)
                )
                .order_by("created_at")
                .select_for_update(skip_locked=True)[:room]
            )
            for row in claimable:
                # Consume the attempt while the row is locked. If this
                # process dies before sending, the row retries after
                # RETRY_WAIT instead of a second runner sending the same
                # mail while the first send is still in flight.
                row.attempts += 1
                row.last_attempt_at = now
                row.save(update_fields=["attempts", "last_attempt_at"])
                rows.append(row)
    return rows


def _send_rows(rows: list[Email]) -> int:
    """Send each claimed row through the `smtp` mailer and save its outcome."""
    sent_now = 0
    try:
        with mail.mailers[MAILER_ALIAS] as backend:
            for row in rows:
                try:
                    delivered = backend.send_messages([build_message(row)])
                except Exception as exc:
                    # A failed connection would fail every later row: force
                    # the next send_messages call to open a fresh one.
                    backend.close()
                    _record_failure(row, str(exc))
                else:
                    if delivered == 1:
                        sent_now += 1
                        row.status = Email.Status.SENT
                        row.sent_at = timezone.now()
                        row.save(update_fields=["status", "sent_at"])
                    else:
                        _record_failure(
                            row,
                            f"backend sent {delivered} message(s) instead of 1",
                        )
    except Exception:
        # open()/QUIT failures escape the per-row handler. The claim is
        # already durable (attempts consumed, rows retry after RETRY_WAIT),
        # so log it and report what was saved so far instead of aborting.
        logger.exception("queue batch aborted by a mailer connection error")
    return sent_now


def _pending_count() -> int:
    """Count the rows still waiting in the queue."""
    return Email.objects.filter(status=Email.Status.PENDING).count()


def _record_failure(row: Email, error: str) -> None:
    """Charge a failed send: the attempt was consumed at claim time."""
    logger.warning("queued email %d failed to send: %s", row.pk, error)
    row.last_error = error[:LAST_ERROR_MAX_CHARS]
    if row.attempts >= MAX_ATTEMPTS:
        row.status = Email.Status.FAILED
    row.last_attempt_at = timezone.now()
    row.save(update_fields=["last_error", "status", "last_attempt_at"])


def requeue_emails(queryset) -> int:
    """Put rows back to `pending` for a resend.

    Only `sent` and `failed` rows are touched: a `pending` row is already
    queued, and recounting it as a resend would bump `resend_count` for
    work nobody asked for. `sent_at` and `last_error` are left as they
    are: a later attempt only overwrites them once it has actually sent.
    """
    return queryset.filter(
        status__in=[Email.Status.SENT, Email.Status.FAILED]
    ).update(
        status=Email.Status.PENDING,
        attempts=0,
        resend_count=models.F("resend_count") + 1,
    )
