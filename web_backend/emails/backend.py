"""The mailer Django's `send` path reaches through. Thin on purpose."""

from django.core.mail.backends.base import BaseEmailBackend

from emails.services import queue_message


class QueueBackend(BaseEmailBackend):
    def send_messages(self, email_messages) -> int:
        count = 0
        for message in email_messages:
            try:
                queue_message(message)
            except Exception:
                # `fail_silently` was requested by the caller; a full mailbox
                # table or a rejected message is a delivery failure like any
                # other and must not burst out of `send()`.
                if not self._fail_silently:
                    raise
            else:
                count += 1
        return count
