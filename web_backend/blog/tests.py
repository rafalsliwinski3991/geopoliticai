"""Tests for the blog: list, archive, detail, markdown, publish gating."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.test import TestCase
from django.urls import reverse

from blog.models import Post


def make_post(
    slug: str,
    title: str,
    days_ago: int,
    *,
    is_published: bool = True,
    body: str = "Body **text**.",
) -> Post:
    return Post.objects.create(
        slug=slug,
        title=title,
        kicker="Method",
        body=body,
        published_at=datetime(2026, 9, 18, 12, 0, tzinfo=UTC) - timedelta(days=days_ago),
        is_published=is_published,
    )


class BlogListTests(TestCase):
    def test_renders_200(self) -> None:
        response = self.client.get(reverse("blog:index"))
        self.assertEqual(response.status_code, 200)

    def test_shows_only_published_posts_newest_first(self) -> None:
        make_post("old", "Published old", 30)
        make_post("new", "Newest note", 1)
        draft = make_post("draft", "Not ready yet", 2, is_published=False)
        response = self.client.get(reverse("blog:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Newest note")
        self.assertEqual(
            [post.slug for post in response.context["posts"]], ["new", "old"]
        )
        self.assertNotContains(response, draft.title)

    def test_detail_renders_markdown(self) -> None:
        make_post("md", "Markdown note", 1, body="# Heading\n\nBody *mark*.")
        response = self.client.get(reverse("blog:detail", args=["md"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1>Heading</h1>")
        self.assertContains(response, "Body <em>mark</em>.")

    def test_unpublished_post_404s(self) -> None:
        make_post("secret", "Hidden note", 1, is_published=False)
        response = self.client.get(reverse("blog:detail", args=["secret"]))
        self.assertEqual(response.status_code, 404)


class BlogRoutingTests(TestCase):
    def test_resolve(self) -> None:
        self.assertEqual(reverse("blog:index"), "/blog/")
        self.assertEqual(reverse("blog:detail", args=["x"]), "/blog/x/")
