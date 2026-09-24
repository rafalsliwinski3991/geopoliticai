"""Admin editing for the blog: the only authoring surface (plan unit 12)."""

from django.contrib import admin

from blog.models import Post


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("title",)}
    list_display = ("title", "slug", "kicker", "published_at", "updated_at", "is_published")
    list_filter = ("is_published",)
