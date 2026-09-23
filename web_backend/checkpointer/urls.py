"""Admin routes for browsing the LangGraph-owned checkpointer tables."""

from django.contrib import admin
from django.urls import path

from .admin import ReadOnlyBrowseOnlyAdmin

urlpatterns = [
    path(
        "<slug:table>/",
        admin.site.admin_view(ReadOnlyBrowseOnlyAdmin.as_view()),
        name="checkpointer-browse",
    ),
]
