from django.apps import AppConfig


class UsersConfig(AppConfig):
    """The project's custom user model, defined before any auth migration."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "users"
