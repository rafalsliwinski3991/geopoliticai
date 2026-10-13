"""Every rule of the outgoing-mail queue.

`queue_message` stores, `build_message` rebuilds, `send_batch` sends,
`requeue_emails` resends. The admin, the management command and the
mail backend hold no rules and only call these.
"""

from datetime import timedelta

from django.conf import settings
from django.core import mail
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.db import models, transaction
from django.utils import timezone

from emails.models import Email

MAX_ATTEMPTS = 3
RETRY_WAIT = timedelta(minutes=5)
SLICE_SIZE = 20
CAP_WINDOW = timedelta(hours=1)
MAILER_ALIAS = "smtp"
LAST_ERROR_MAX_CHARS = 2000


def queue_message(message: EmailMessage) -> Email:
    """Store one outgoing message as a `pending` row instead of sending it."""
    if getattr(message, "attachments", None):
        raise ValueError("queued mail cannot carry attachments")
    if message.extra_headers:
        raise ValueError(
            "queued mail cannot carry extra headers: "
            + ", ".join(sorted(message.extra_headers))
        )
    alternatives = [
        (content, mimetype)
        for content, mimetype in getattr(message, "alternatives", [])
        if mimetype != "text/html"
    ]
    if alternatives:
        raise ValueError(
            "queued mail can only carry text/html alternatives, not "
            + alternatives[0][1]
        )
    html = next(
        (
            content
            for content, mimetype in getattr(message, "alternatives", [])
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
    """
    now = timezone.now()
    sent_in_window = Email.objects.filter(sent_at__gt=now - CAP_WINDOW).count()
    room = min(SLICE_SIZE, settings.EMAIL_MAX_PER_HOUR - sent_in_window)
    sent_now = 0
    if room > 0:
        with transaction.atomic():
            rows = (
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
            with mail.mailers[MAILER_ALIAS] as backend:
                for row in rows:
                    try:
                        backend.send_messages([build_message(row)])
                    except Exception as exc:
                        row.attempts += 1
                        row.last_attempt_at = now
                        row.last_error = str(exc)[:LAST_ERROR_MAX_CHARS]
                        if row.attempts >= MAX_ATTEMPTS:
                            row.status = Email.Status.FAILED
                        row.save()
                    else:
                        sent_now += 1
                        row.status = Email.Status.SENT
                        row.attempts += 1
                        row.sent_at = now
                        row.last_attempt_at = now
                        row.save()
    still_pending = Email.objects.filter(status=Email.Status.PENDING).count()
    return sent_now, still_pending


def requeue_emails(queryset) -> int:
    """Put rows back to `pending` for a resend.

    `sent_at` and `last_error` are left as they are: a later attempt only
    overwrites them once it has actually sent.
    """
    return queryset.update(
        status=Email.Status.PENDING,
        attempts=0,
        resend_count=models.F("resend_count") + 1,
    )
