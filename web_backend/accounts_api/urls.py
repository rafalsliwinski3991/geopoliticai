"""URL routing for the accounts_api app."""

from django.urls import path

from accounts_api import views

urlpatterns = [
    path("token/", views.token, name="token"),
]
