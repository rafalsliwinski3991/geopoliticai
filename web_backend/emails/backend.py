"""The mailer Django's `send` path reaches through. Thin on purpose."""

from django.core.mail.backends.base import BaseEmailBackend

from emails.services import queue_message


class QueueBackend(BaseEmailBackend):
    def send_messages(self, email_messages) -> int:
        count = 0
        for message in email_messages:
            queue_message(message)
            count += 1
        return count
