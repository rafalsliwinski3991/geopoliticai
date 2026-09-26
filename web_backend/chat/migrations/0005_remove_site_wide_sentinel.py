"""Retire the site-wide sentinel user (#66).

`site_quota` holds the site ceiling now; nothing reads user 0. This makes
0002's "nothing may ever delete this row" historical. Raw SQL because
Django's FK cascade is ORM-emulated and the database FK has no ON DELETE
CASCADE: the quota rows go first. The reverse re-creates the sentinel
exactly as 0002 did, so a local `migrate chat 0004` round-trips; production
rollbacks restore snapshots instead.
"""

from django.db import migrations

SENTINEL_USER_ID = 0
SENTINEL_EMAIL = "site-wide-quota@politicalagent.eu"


def remove_sentinel(apps, schema_editor) -> None:
    """Delete the sentinel's quota rows, then the sentinel user."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DELETE FROM quota WHERE user_id = %s", (SENTINEL_USER_ID,))
        cursor.execute("DELETE FROM users_user WHERE id = %s", (SENTINEL_USER_ID,))


def restore_sentinel(apps, schema_editor) -> None:
    """Re-create the sentinel exactly as 0002 did."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO users_user (
                id, password, is_superuser, is_staff, is_active, date_joined,
                email, first_name, last_name
            )
            VALUES (
                %s, '!sentinel-site-wide-quota-not-a-real-hash', FALSE, FALSE,
                FALSE, NOW(), %s, '', ''
            )
            ON CONFLICT (id) DO NOTHING
            """,
            (SENTINEL_USER_ID, SENTINEL_EMAIL),
        )


class Migration(migrations.Migration):
    dependencies = [("chat", "0004_copy_site_quota"), ("users", "0001_initial")]

    operations = [migrations.RunPython(remove_sentinel, restore_sentinel)]
