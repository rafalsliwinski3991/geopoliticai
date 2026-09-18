"""URL routing for the Django service."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Listed first so `token/` is matched before allauth's catch-all patterns.
    path("accounts/", include("accounts_api.urls")),
    path("accounts/", include("allauth.urls")),
]
