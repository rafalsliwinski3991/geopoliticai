"""URL routing for the Django service."""

from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from pages.sitemaps import PostSitemap, StaticSitemap

SITEMAPS = {"static": StaticSitemap, "posts": PostSitemap}

urlpatterns = [
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="django.contrib.sitemaps.views.sitemap"),
    # Django owns `/` from unit 11: the landing page, then the blog (unit 12).
    path("", include("pages.urls")),
    # Unit 12: the public notes section under its own app.
    path("blog/", include("blog.urls")),
    # This route must precede the admin's permissive model/object URL patterns.
    path("admin/checkpointer/", include("checkpointer.urls")),
    path("admin/", admin.site.urls),
    # Listed first so `token/` is matched before allauth's catch-all patterns.
    path("accounts/", include("accounts_api.urls")),
    path("accounts/", include("allauth.urls")),
]
