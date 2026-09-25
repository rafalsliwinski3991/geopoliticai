"""Tests for the blog views: list, archive, detail, publish gating (unit 12)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import mock

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
    summary: str = "",
) -> Post:
    return Post.objects.create(
        slug=slug,
        title=title,
        kicker="Method",
        body=body,
        summary=summary,
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

    def test_a_post_becomes_visible_once_its_timestamp_passes(self) -> None:
        """A post dated after the process started must appear once its
        timestamp passes: the queryset's cutoff cannot stay frozen at import."""
        # Arrange
        make_post("scheduled", "Scheduled reveal", 1)
        Post.objects.filter(slug="scheduled").update(
            published_at=_now_utc() + timedelta(hours=1)
        )

        # Act
        with mock.patch(
            "django.utils.timezone.now",
            return_value=_now_utc() + timedelta(hours=2),
        ):
            response = self.client.get(reverse("blog:index"))

        # Assert
        self.assertContains(response, "Scheduled reveal")


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
        self.assertNotContains(response, "No posts yet")

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

    def test_the_index_labels_each_post_as_ai_generated(self) -> None:
        # Arrange
        make_post("one", "First post", 2)
        make_post("two", "Second post", 1)

        # Act
        response = self.client.get(reverse("blog:index"))

        # Assert
        # One `.ai-label` paragraph per card: the lead and the one archive
        # entry. (The intro sentence also says "AI-generated text", so the
        # plan's literal-string count of two cannot hold against the plan's
        # own template; the label markup is what unit 04's CSS targets.)
        self.assertEqual(response.content.count(b'<p class="ai-label">'), 2)

    def test_the_index_shows_the_summary_text_when_set(self) -> None:
        # Arrange
        make_post("sum", "Summary post", 1, summary="A custom summary line.")

        # Act
        response = self.client.get(reverse("blog:index"))

        # Assert
        self.assertContains(response, "A custom summary line.")

    def test_the_navigation_and_footer_say_blog(self) -> None:
        # Arrange
        # Act
        response = self.client.get(reverse("blog:index"))

        # Assert
        self.assertContains(response, ">Blog<")
        self.assertNotContains(response, ">Notes<")

    def test_the_subscribe_paragraph_has_no_orphaned_period(self) -> None:
        # Arrange
        make_post("sub", "Subscribe post", 1)

        # Act
        response = self.client.get(reverse("blog:index"))

        # Assert
        self.assertNotContains(response, "</a>.")


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

    def test_the_detail_label_sits_between_the_headline_and_the_body(self) -> None:
        """EU AI Act Art. 50(4): the disclosure is at first exposure, directly
        under the headline and before the body starts."""
        # Arrange
        make_post("label", "Labelled post", 1)

        # Act
        response = self.client.get(reverse("blog:detail", args=["label"]))
        html = response.content.decode()

        # Assert
        self.assertIn("<h1>Labelled post</h1>", html)
        self.assertIn('<p class="ai-label">AI-generated text</p>', html)
        self.assertIn('<div class="post-body">', html)
        self.assertLess(html.index("<h1>"), html.index("AI-generated text"))
        self.assertLess(html.index("AI-generated text"), html.index('<div class="post-body">'))

    def test_the_detail_names_the_editorial_byline_and_links_the_chat(self) -> None:
        # Arrange
        make_post("byline", "Byline post", 1)

        # Act
        response = self.client.get(reverse("blog:detail", args=["byline"]))

        # Assert
        self.assertContains(response, "PoliticalAgent editorial")
        self.assertContains(response, 'href="/chat"')


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
