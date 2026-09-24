"""Point the sites framework at the public host.

The sitemap view builds absolute URLs from `Site(SITE_ID)`, and allauth puts
its name in email subjects; the post_migrate default is `example.com`.
"""

from urllib.parse import urlsplit

from django.conf import settings
from django.db import migrations


def set_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.update_or_create(
        id=settings.SITE_ID,
        defaults={"domain": urlsplit(settings.SITE_ORIGIN).netloc, "name": "PoliticalAgent"},
    )


class Migration(migrations.Migration):

    dependencies = [
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [
        migrations.RunPython(set_site, migrations.RunPython.noop),
    ]
