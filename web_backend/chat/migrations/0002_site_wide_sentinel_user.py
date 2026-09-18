"""The site-wide quota ceiling needs a reserved identity (unit 6).

`Quota.user` is a foreign key to `users_user`, so the sentinel user id that
`agentic_backend`'s site-wide ceiling spends against must exist. 0 is chosen
because Django's BigAutoField sequences start at 1: no real signup can ever
collide with it. Nothing may ever delete this row — it is not a person.
"""

from django.db import connection
from django.db import migrations

SENTINEL_USER_ID = 0
SENTINEL_EMAIL = "site-wide-quota@politicalagent.eu"


def insert_sentinel(apps, schema_editor) -> None:
    """Insert the reserved identity, idempotently, bypassing the ORM."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO users_user (
                id, password, is_superuser, is_staff, is_active, date_joined,
                email, first_name, last_name
            )
            VALUES (
                %s, '!sentinel-site-wide-quota-not-a-real-hash', FALSE, FALSE,
                TRUE, NOW(), %s, '', ''
            )
            ON CONFLICT (id) DO NOTHING
            """,
            (SENTINEL_USER_ID, SENTINEL_EMAIL),
        )


def remove_sentinel(apps, schema_editor) -> None:
    """Reverse migration only; the sentinel is never deleted in production."""
    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM users_user WHERE id = %s", (SENTINEL_USER_ID,)
        )


class Migration(migrations.Migration):
    dependencies = [
        ("chat", "0001_initial"),
        ("users", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(insert_sentinel, remove_sentinel),
    ]
