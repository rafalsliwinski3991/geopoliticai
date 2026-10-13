"""The MAILERS wiring in `politicalagent/settings.py` itself.

The test runner replaces every `MAILERS` alias with locmem, so these
tests read the module value directly instead of `django.conf.settings`.
"""

import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


def read_settings_expression(expression: str) -> str:
    web_backend = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import politicalagent.settings as s; print({expression})",
        ],
        cwd=web_backend,
        env={**os.environ},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class MailersSettingsTest(SimpleTestCase):
    def test_default_mailer_is_the_queue_backend(self) -> None:
        # Arrange
        # Act
        default = read_settings_expression("s.MAILERS['default']['BACKEND']")
        # Assert
        self.assertEqual(default, "emails.backend.QueueBackend")

    def test_smtp_mailer_carries_the_domain_mailbox_options(self) -> None:
        # Arrange
        # Act
        smtp = read_settings_expression("sorted(s.MAILERS['smtp']['OPTIONS'])")
        # Assert
        self.assertEqual(
            smtp,
            "['host', 'password', 'port', 'use_tls', 'username']",
        )

    def test_email_max_per_hour_is_a_positive_int(self) -> None:
        # Arrange
        # Act
        raw = read_settings_expression("s.EMAIL_MAX_PER_HOUR")
        # Assert
        self.assertTrue(int(raw) > 0)
