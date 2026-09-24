"""Views for the public site pages."""

from __future__ import annotations

from django.views import generic

from blog.models import Post
from pages.consts import LANDING_SECTIONS


class LandingView(generic.TemplateView):
    template_name = "pages/landing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["LANDING_SECTIONS"] = LANDING_SECTIONS
        context["total_domains"] = LANDING_SECTIONS.total
        return context


class RobotsView(generic.TemplateView):
    template_name = "pages/robots.txt"
    content_type = "text/plain; charset=utf-8"


class LlmsView(generic.TemplateView):
    template_name = "pages/llms.txt"
    content_type = "text/plain; charset=utf-8"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["posts"] = Post.objects.published()
        context["total_domains"] = LANDING_SECTIONS.total
        return context
