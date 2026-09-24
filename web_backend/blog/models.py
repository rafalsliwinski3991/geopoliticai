"""The blog's plain-Django content model (plan §7): no taxonomy, no plugins.

Posts are author-only and editable solely through the admin, which is why the
detail view renders the body's Markdown with `mark_safe` rather than
sanitizing it. That trust has exactly one author; if the blog ever gains a
second one, the model above must grow a sanitizing filter (plan §3 unit 12).
"""

from __future__ import annotations

import html
import markdown

from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import Truncator


class PostQuerySet(models.QuerySet):
    def published(self) -> PostQuerySet:
        # `now()` runs per call, never at import: a post dated after the
        # process started must appear once its timestamp passes.
        return self.filter(is_published=True, published_at__lte=timezone.now())


class Post(models.Model):
    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=200)
    kicker = models.CharField(max_length=120, blank=True)
    summary = models.CharField(
        max_length=160,
        blank=True,
        help_text="Up to 160 characters. Shown in search results, link previews and the blog index.",
    )
    body = models.TextField()
    published_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)
    is_published = models.BooleanField(default=False)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at"]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("blog:detail", args=[self.slug])

    def description(self) -> str:
        """The summary, or the body's first 30 words as plain text."""
        if self.summary:
            return self.summary
        # Markdown emits entities (`&amp;`); unescape so templates escape once.
        return Truncator(html.unescape(strip_tags(markdown.markdown(self.body)))).words(30)
