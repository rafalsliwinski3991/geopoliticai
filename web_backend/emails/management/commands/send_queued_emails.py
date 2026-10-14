from django.core.management.base import BaseCommand

from emails.services import send_batch


class Command(BaseCommand):
    help = "Send one slice of queued email."

    def handle(self, *args, **options) -> None:
        sent, pending = send_batch()
        self.stdout.write(f"sent {sent}, pending {pending}")
