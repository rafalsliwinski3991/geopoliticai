"""Routing for the blog."""

from django.urls import path

from blog import views

app_name = "blog"

urlpatterns = [
    path("", views.BlogIndexView.as_view(), name="index"),
    path("<slug:slug>/", views.BlogDetailView.as_view(), name="detail"),
]
