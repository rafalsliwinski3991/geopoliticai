"""Tests for the blog views: list, archive, detail, publish gating (unit 12)."""

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
        # Arrange
        # Act
        response = self.client.get(reverse("blog:index"))
        # Assert
        self.assertEqual(response.status_code, 200)

    def test_shows_only_published_posts_newest_first(self) -> None:
        # Arrange
        make_post("old", "Published old", 30)
        make_post("new", "Newest note", 1)
        draft = make_post("draft", "Not ready yet", 2, is_published=False)

        # Act
        response = self.client.get(reverse("blog:index"))

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Newest note")
        self.assertEqual(
            [post.slug for post in response.context["posts"]], ["new", "old"]
        )
        self.assertNotContains(response, draft.title)

    def test_a_scheduled_post_stays_hidden_until_its_timestamp(self) -> None:
        """`published_at` in the future must not ship now, and must never sit
        in the lead slot ahead of a genuinely published note."""
        # Arrange
        scheduled = make_post("scheduled", "Not yet", 3)
        Post.objects.filter(slug="scheduled").update(
            published_at=_now_utc() + timedelta(days=7)
        )

        # Act
        response = self.client.get(reverse("blog:index"))

        # Assert
        self.assertNotContains(response, scheduled.title)
        self.assertEqual(list(response.context["posts"]), [])

    def test_detail_renders_markdown(self) -> None:
        # Arrange
        make_post("md", "Markdown note", 1, body="# Heading\n\nBody *mark*.")

        # Act
        response = self.client.get(reverse("blog:detail", args=["md"]))

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<h1>Heading</h1>")
        self.assertContains(response, "Body <em>mark</em>.")

    def test_a_single_post_does_not_show_the_empty_state(self) -> None:
        # Arrange
        make_post("only", "Lone note", 1)

        # Act
        response = self.client.get(reverse("blog:index"))

        # Assert
        self.assertContains(response, "Lone note")
        self.assertNotContains(response, "No notes yet")

    def test_teasers_do_not_leak_markdown_syntax(self) -> None:
        # Arrange
        make_post("m", "Markdown teasers", 1, body="# Heading\n\nBody *mark*.")

        # Act
        response = self.client.get(reverse("blog:index"))

        # Assert
        self.assertNotContains(response, "**")
        self.assertNotContains(response, "[Heading](#)")

    def test_unpublished_post_404s(self) -> None:
        # Arrange
        make_post("secret", "Hidden note", 1, is_published=False)

        # Act
        response = self.client.get(reverse("blog:detail", args=["secret"]))

        # Assert
        self.assertEqual(response.status_code, 404)


class BlogDetailTests(TestCase):
    def test_the_detail_page_renders_the_post_title_as_its_headline(self) -> None:
        """`Post.title` is the page heading; the body cannot be assumed to
        repeat it as a Markdown heading."""
        # Arrange
        make_post("md", "The headlined note", 1, body="# Heading\n\nBody *mark*.")

        # Act
        response = self.client.get(reverse("blog:detail", args=["md"]))

        # Assert
        self.assertContains(response, "The headlined note")


class BlogRoutingTests(TestCase):
    def test_resolve(self) -> None:
        # Arrange
        # Act
        index = reverse("blog:index")
        detail = reverse("blog:detail", args=["x"])
        # Assert
        self.assertEqual(index, "/blog/")
        self.assertEqual(detail, "/blog/x/")


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)
