"""Carry the sentinel's site-wide counts into `site_quota` (#66).

Today's row is what keeps the ceiling honest across the deploy; older rows
keep the admin history. 0005 then deletes the sentinel.
"""

from django.db import migrations

SENTINEL_USER_ID = 0


def copy_sentinel_rows(apps, schema_editor) -> None:
    """Copy every sentinel quota row into site_quota."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO site_quota (day, used) "
            "SELECT day, used FROM quota WHERE user_id = %s",
            (SENTINEL_USER_ID,),
        )


class Migration(migrations.Migration):
    dependencies = [("chat", "0003_site_quota")]

    # Reverse is a no-op: reversing 0003 drops the table and its rows.
    operations = [migrations.RunPython(copy_sentinel_rows, migrations.RunPython.noop)]
