"""The blog's plain-Django content model (plan §7): no taxonomy, no plugins.

Posts are author-only and editable solely through the admin, which is why the
detail view renders the body's Markdown with `mark_safe` rather than
sanitizing it. That trust has exactly one author; if the blog ever gains a
second one, the model above must grow a sanitizing filter (plan §3 unit 12).
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


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
