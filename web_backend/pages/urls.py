"""Routing for the public site pages."""

from django.urls import path

from pages import views

app_name = "pages"

urlpatterns = [
    path("", views.LandingView.as_view(), name="landing"),
    path("robots.txt", views.RobotsView.as_view(), name="robots"),
    path("llms.txt", views.LlmsView.as_view(), name="llms"),
    path("about/", views.AboutView.as_view(), name="about"),
    path("privacy/", views.PrivacyView.as_view(), name="privacy"),
]
