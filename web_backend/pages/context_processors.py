"""Template context shared by every server-rendered page."""

from django.conf import settings


def site_origin(request):
    return {"SITE_ORIGIN": settings.SITE_ORIGIN}
