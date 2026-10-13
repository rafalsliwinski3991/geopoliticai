"""The MAILERS wiring in `politicalagent/settings.py` itself.

The test runner replaces every `MAILERS` alias with locmem, so these
tests read the module value directly instead of `django.conf.settings`.
"""

import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


def read_settings_expression(expression: str, env: dict[str, str] | None = None) -> str:
    web_backend = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import politicalagent.settings as s; print({expression})",
        ],
        cwd=web_backend,
        # Settings load the repo .env themselves, but load_dotenv() only
        # fills variables the subprocess environment does not have yet, so
        # passing a value here always wins and keeps the run deterministic.
        env={**os.environ, **(env or {})},
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
        smtp_backend = "django.core.mail.backends.smtp.EmailBackend"
        # Act
        smtp = read_settings_expression(
            "sorted(s.MAILERS['smtp']['OPTIONS'])",
            env={"DJANGO_EMAIL_BACKEND": smtp_backend},
        )
        # Assert
        self.assertEqual(
            smtp,
            "['host', 'password', 'port', 'timeout', 'use_tls', 'username']",
        )

    def test_the_smtp_options_carry_the_env_values_with_no_override(self) -> None:
        # Arrange
        env = {
            "DJANGO_EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_PORT": "2525",
            "EMAIL_USE_TLS": "false",
            "EMAIL_MAX_PER_HOUR": "17",
        }
        # Act
        port = read_settings_expression(
            "s.MAILERS['smtp']['OPTIONS']['port']", env=env
        )
        use_tls = read_settings_expression(
            "s.MAILERS['smtp']['OPTIONS']['use_tls']", env=env
        )
        max_per_hour = read_settings_expression("s.EMAIL_MAX_PER_HOUR", env=env)
        # Assert
        self.assertEqual(port, "2525")
        self.assertEqual(use_tls, "False")
        self.assertEqual(max_per_hour, "17")

    def test_the_console_override_selects_that_backend_without_smtp_options(self) -> None:
        # Arrange
        # what .env.example sets for development; SMTP OPTIONS would make
        # Django raise InvalidMailer for unknown options on the console
        # backend, so the override must come without them.
        env = {
            "DJANGO_EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend"
        }
        # Act
        backend = read_settings_expression("s.MAILERS['smtp']['BACKEND']", env=env)
        options = read_settings_expression("s.MAILERS['smtp']['OPTIONS']", env=env)
        # Assert
        self.assertEqual(
            backend, "django.core.mail.backends.console.EmailBackend"
        )
        self.assertEqual(options, "{}")

    def test_email_max_per_hour_is_a_positive_int(self) -> None:
        # Arrange
        # Act
        raw = read_settings_expression("s.EMAIL_MAX_PER_HOUR")
        # Assert
        self.assertTrue(int(raw) > 0)
