"""Tests for `PostQuerySet.published()` — the single definition of "live" (unit 01)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.test import TestCase

from blog.models import Post


def _now() -> datetime:
    return datetime.now(tz=UTC)


class PublishedQuerySetTests(TestCase):
    def test_published_excludes_drafts_and_future_posts_and_includes_a_past_post(
        self,
    ) -> None:
        # Arrange
        past = Post.objects.create(
            slug="past",
            title="Past",
            body="Body.",
            published_at=_now() - timedelta(days=1),
            is_published=True,
        )
        Post.objects.create(
            slug="draft",
            title="Draft",
            body="Body.",
            published_at=_now() - timedelta(days=1),
            is_published=False,
        )
        Post.objects.create(
            slug="future",
            title="Future",
            body="Body.",
            published_at=_now() + timedelta(days=1),
            is_published=True,
        )

        # Act
        result = Post.objects.published()

        # Assert
        self.assertEqual(list(result), [past])


def _post(slug: str, *, summary: str = "", body: str = "Body.") -> Post:
    return Post.objects.create(
        slug=slug,
        title=slug,
        summary=summary,
        body=body,
        published_at=_now() - timedelta(days=1),
        is_published=True,
    )


class DescriptionTests(TestCase):
    def test_description_returns_the_summary_when_set(self) -> None:
        # Arrange
        post = _post("summarised", summary="A hand-written summary.")

        # Act
        # Assert
        self.assertEqual(post.description(), "A hand-written summary.")

    def test_description_falls_back_to_plain_body_text_within_30_words(self) -> None:
        # Arrange
        post = _post("fallback", body="# Heading\n\nBody *mark* with <b>html</b> entities & more.")

        # Act
        description = post.description()

        # Assert
        self.assertNotIn("#", description)
        self.assertNotIn("*", description)
        self.assertNotIn("<", description)
        self.assertNotIn("&amp;", description)
        self.assertLessEqual(len(description.split()), 30)
