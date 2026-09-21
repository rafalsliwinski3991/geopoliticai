"""App config for `chat`, whose only job is to connect the delete cascade."""

from django.apps import AppConfig


class ChatConfig(AppConfig):
    """Import the signal handlers when the app registry is ready."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "chat"

    def ready(self) -> None:
        """Connect `pre_delete` by importing the module that registers it."""
        from chat import signals  # noqa: F401
