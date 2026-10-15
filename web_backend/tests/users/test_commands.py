import os
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from users.models import User

ENV = {"E2E_EMAIL": "e2e@example.com", "E2E_PASSWORD": "s3cret-pass-1"}


class CreateE2eUserCommandTests(TestCase):
    @override_settings(DEBUG=False)
    def test_command_refuses_when_debug_is_off(self):
        # Arrange
        with mock.patch.dict(os.environ, ENV):
            # Act
            with self.assertRaisesMessage(CommandError, "DEBUG is off"):
                call_command("create_e2e_user", stdout=StringIO())

        # Assert
        self.assertFalse(User.objects.exists())

    @override_settings(DEBUG=True)
    def test_command_refuses_without_the_env_vars(self):
        # Arrange
        with mock.patch.dict(os.environ, ENV):
            os.environ.pop("E2E_EMAIL")

            # Act
            with self.assertRaisesMessage(CommandError, "Set E2E_EMAIL and E2E_PASSWORD"):
                call_command("create_e2e_user", stdout=StringIO())

        # Assert
        self.assertFalse(User.objects.exists())

    @override_settings(DEBUG=True)
    def test_command_refuses_without_the_password(self):
        # Arrange
        with mock.patch.dict(os.environ, ENV):
            os.environ.pop("E2E_PASSWORD")

            # Act
            with self.assertRaisesMessage(CommandError, "Set E2E_EMAIL and E2E_PASSWORD"):
                call_command("create_e2e_user", stdout=StringIO())

        # Assert
        self.assertFalse(User.objects.exists())

    @override_settings(DEBUG=True)
    def test_command_creates_the_user_and_prints_no_password(self):
        # Arrange
        out = StringIO()

        # Act
        with mock.patch.dict(os.environ, ENV):
            call_command("create_e2e_user", stdout=out)

        # Assert
        self.assertEqual(out.getvalue().strip(), "E2E user ready: e2e@example.com")
        self.assertNotIn(ENV["E2E_PASSWORD"], out.getvalue())
        self.assertTrue(User.objects.filter(email="e2e@example.com").exists())
