"""URL routing for the Django service."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Django owns `/` from unit 11: the landing page, then the blog (unit 12).
    path("", include("pages.urls")),
    # Unit 12: the public notes section under its own app.
    path("blog/", include("blog.urls")),
    path("admin/", admin.site.urls),
    # Listed first so `token/` is matched before allauth's catch-all patterns.
    path("accounts/", include("accounts_api.urls")),
    path("accounts/", include("allauth.urls")),
]
