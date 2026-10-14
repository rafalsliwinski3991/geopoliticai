from django.db import models


class Email(models.Model):
    """One outgoing mail Django queued instead of sending over SMTP.

    Every row is created by `emails.services.queue_message`; nobody adds
    them by hand, so the admin is read-only apart from the resend action.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        SENT = "sent"
        FAILED = "failed"

    created_at = models.DateTimeField(auto_now_add=True)
    from_email = models.CharField(max_length=320)
    to = models.JSONField()
    cc = models.JSONField(default=list, blank=True)
    bcc = models.JSONField(default=list, blank=True)
    reply_to = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=998)
    body = models.TextField(blank=True)
    html = models.TextField(blank=True)
    status = models.CharField(
        max_length=10, choices=Status, default=Status.PENDING
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    resend_count = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "created_at"], name="emails_email_status_created"
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "sent", "failed"]),
                name="emails_email_status_valid",
            )
        ]

    def __str__(self) -> str:
        return f"{self.subject} -> {', '.join(self.to)}"
