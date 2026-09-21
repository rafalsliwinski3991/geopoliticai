"""Views for the public site pages."""

from __future__ import annotations

from django.views import generic

from pages.consts import LANDING_SECTIONS


class LandingView(generic.TemplateView):
    template_name = "pages/landing.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["LANDING_SECTIONS"] = LANDING_SECTIONS
        context["total_domains"] = LANDING_SECTIONS.total
        return context
