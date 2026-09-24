"""Sitemaps for the public site. Google ignores changefreq and priority, so neither is set."""

from __future__ import annotations

from blog.models import Post
from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticSitemap(Sitemap):
    protocol = "https"

    def items(self):
        return ["pages:landing", "blog:index"]

    def location(self, item):
        return reverse(item)


class PostSitemap(Sitemap):
    protocol = "https"

    def items(self):
        return Post.objects.published()

    def lastmod(self, post):
        return post.updated_at
