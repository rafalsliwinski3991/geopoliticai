"""Views for the blog (index + detail), fed from the admin's posts."""

from __future__ import annotations

from blog.models import Post
from django.views import generic


class BlogIndexView(generic.ListView):
    template_name = "blog/index.html"
    context_object_name = "posts"

    def get_queryset(self):
        return Post.objects.published()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # The lead post is the only full-width treatment; the rest is archive.
        published = list(context["object_list"])
        context["lead"] = published[0] if published else None
        context["archive_posts"] = published[1:]
        return context


class BlogDetailView(generic.DetailView):
    template_name = "blog/detail.html"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        # Unpublished and future-dated posts 404, exactly like the list skips them.
        return Post.objects.published()
