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


class PurgeStatementsTest(TestCase):
    """The statements a thread or user deletion runs against the `agentic` schema."""

    def test_a_purge_deletes_the_uploaded_document_chunks_too(self) -> None:
        # The chunks hold the full text of a user's upload, keyed by a bare
        # thread_id like the checkpoints; deleting the thread must reach them.
        # Arrange
        where = "thread_id = %s"

        # Act
        statements = signals.purge_statements(where)

        # Assert
        self.assertIn(
            "DELETE FROM agentic.document_chunks WHERE thread_id = %s", statements
        )
