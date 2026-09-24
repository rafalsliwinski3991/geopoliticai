"""Sitemaps for the public site. Google ignores changefreq and priority, so neither is set."""

from __future__ import annotations

from urllib.parse import urlsplit

from blog.models import Post
from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class OriginSitemap(Sitemap):
    """Hosts URLs from SITE_ORIGIN like robots.txt and canonical, not the editable Site row."""

    protocol = "https"

    def get_domain(self, site=None):
        return urlsplit(settings.SITE_ORIGIN).netloc


class StaticSitemap(OriginSitemap):

    def items(self):
        return ["pages:landing", "blog:index", "pages:about", "pages:privacy"]

    def location(self, item):
        return reverse(item)


class PostSitemap(OriginSitemap):
    def items(self):
        return Post.objects.published()

    def lastmod(self, post):
        return post.updated_at
