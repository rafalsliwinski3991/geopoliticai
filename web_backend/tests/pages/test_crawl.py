"""Tests for the crawl files: /robots.txt, /sitemap.xml, /llms.txt (unit 05)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.contrib.sites.models import Site
from django.test import TestCase
from django.urls import reverse

from blog.models import Post


def _now() -> datetime:
    return datetime.now(tz=UTC)


def make_post(
    slug: str,
    title: str,
    *,
    days_ago: int = 1,
    is_published: bool = True,
) -> Post:
    return Post.objects.create(
        slug=slug,
        title=title,
        kicker="Trade",
        body="Body.",
        published_at=_now() - timedelta(days=days_ago),
        is_published=is_published,
    )


class RobotsTests(TestCase):
    def test_robots_txt_allows_the_public_site_and_disallows_the_private_routes(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/robots.txt")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response["Content-Type"])
        body = response.content.decode()
        self.assertIn("Disallow: /admin/", body)
        self.assertIn("Disallow: /api/", body)
        self.assertIn("Sitemap: https://politicalagent.eu/sitemap.xml", body)
        self.assertNotIn("Disallow: /chat", body)


class SitemapTests(TestCase):
    def test_the_sitemap_lists_the_site_and_blog_urls_behind_tls(self) -> None:
        # Arrange
        published = make_post("published-post", "Published post")
        make_post("a-draft", "A draft", is_published=False)
        future = make_post("a-future-post", "A future post", days_ago=-1)

        # Act
        response = self.client.get("/sitemap.xml", secure=True)
        body = response.content.decode()

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIn("<urlset", body)
        self.assertIn("https://politicalagent.eu/", body)
        self.assertIn("https://politicalagent.eu/blog/", body)
        self.assertIn("https://politicalagent.eu/blog/published-post/", body)
        self.assertIn("<lastmod>", body)
        self.assertNotIn("a-draft", body)
        self.assertNotIn("a-future-post", body)
        self.assertNotIn("example.com", body)


    def test_sitemap_hosts_urls_from_site_origin_not_the_editable_site_row(self) -> None:
        # Arrange
        Site.objects.update(domain="edited.example")
        Site.objects.clear_cache()
        self.addCleanup(Site.objects.clear_cache)

        # Act
        response = self.client.get("/sitemap.xml", secure=True)
        body = response.content.decode()

        # Assert
        self.assertIn("https://politicalagent.eu/blog/", body)
        self.assertNotIn("edited.example", body)


class LlmsTests(TestCase):
    def test_llms_txt_lists_published_post_titles_verbatim(self) -> None:
        # Arrange
        published = make_post("peers-rivals", "Peers & Rivals", days_ago=2)
        make_post("a-draft", "Draft & hidden", is_published=False)
        make_post("a-future-post", "Future & hidden", days_ago=-1)

        # Act
        response = self.client.get("/llms.txt")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response["Content-Type"])
        body = response.content.decode()
        self.assertIn(published.title, body)
        self.assertNotIn("&amp;", body)
        self.assertNotIn("Draft &", body)
        self.assertNotIn("Future", body)
