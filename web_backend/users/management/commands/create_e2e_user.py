"""Create or reset the end-to-end test user from E2E_EMAIL and E2E_PASSWORD.

Development only: it refuses when DEBUG is off, so it can never plant a
known-password account in production. Run it with `make e2e-user`.
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from users.services import ensure_e2e_user


class Command(BaseCommand):
    """Create or reset the E2E test user (development only)."""

    help = __doc__

    def handle(self, *args, **options) -> None:
        if not settings.DEBUG:
            raise CommandError("Refusing to create the E2E user: DEBUG is off (development only).")
        email = os.environ.get("E2E_EMAIL", "")
        password = os.environ.get("E2E_PASSWORD", "")
        if not email or not password:
            raise CommandError("Set E2E_EMAIL and E2E_PASSWORD in the root .env first.")
        user = ensure_e2e_user(email, password)
        self.stdout.write(f"E2E user ready: {user.email}")
