"""Views for the blog (index + detail), fed from the admin's posts."""

from __future__ import annotations

from blog.models import Post
from django.conf import settings
from django.templatetags.static import static
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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        post = context["post"]
        origin = settings.SITE_ORIGIN
        context["structured_data"] = {
            "@context": "https://schema.org",
            "@type": "BlogPosting",
            "headline": post.title,
            "description": post.description(),
            "datePublished": post.published_at.isoformat(),
            "dateModified": post.updated_at.isoformat(),
            "image": f"{origin}{static('site/og-card.png')}",
            "author": {"@type": "Organization", "name": "PoliticalAgent editorial", "url": f"{origin}/blog/"},
            "publisher": {
                "@type": "Organization",
                "name": "PoliticalAgent",
                "url": f"{origin}/",
                "logo": {"@type": "ImageObject", "url": f"{origin}{static('site/logo-512.png')}"},
            },
            "mainEntityOfPage": f"{origin}{post.get_absolute_url()}",
        }
        return context
