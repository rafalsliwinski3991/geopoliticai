"""App config for `checkpointer`, the admin's read-only window onto LangGraph's tables."""

from django.apps import AppConfig


class CheckpointerConfig(AppConfig):
    """No models or signals; browse pages query LangGraph's tables with SQL."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "checkpointer"
