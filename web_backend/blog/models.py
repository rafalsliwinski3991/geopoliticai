"""The blog's plain-Django content model (plan §7): no taxonomy, no plugins.

Posts are author-only and editable solely through the admin, which is why the
detail view renders the body's Markdown with `mark_safe` rather than
sanitizing it. That trust has exactly one author; if the blog ever gains a
second one, the model above must grow a sanitizing filter (plan §3 unit 12).
"""

from __future__ import annotations

from django.db import models


class Post(models.Model):
    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=200)
    kicker = models.CharField(max_length=120, blank=True)
    body = models.TextField()
    published_at = models.DateTimeField()
    is_published = models.BooleanField(default=False)

    class Meta:
        ordering = ["-published_at"]

    def __str__(self) -> str:
        return self.title
