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
