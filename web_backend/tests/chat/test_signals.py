"""Tests for the checkpoint-purge deletion signals (unit 4)."""

from django.contrib.auth import get_user_model
from django.db.models.signals import pre_delete
from django.test import TestCase

from chat import signals

User = get_user_model()


class DeleteSignalTest(TestCase):
    """The pre_delete receiver is registered against the project's user model."""

    def test_receiver_is_connected(self) -> None:
        # A missing ChatConfig.ready() import fails nothing else: models pass,
        # migrations apply, and the data quietly survives the delete.
        # Arrange
        # Act
        sync_receivers, _ = pre_delete._live_receivers(User)

        # Assert
        self.assertIn(signals.delete_checkpointed_messages, sync_receivers)
