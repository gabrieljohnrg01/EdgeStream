from django.contrib import admin
from .models import CatalogTitle, PlaybackProgress, TransientStreamSession, UserProfile, WatchlistItem
@admin.register(CatalogTitle)
class CatalogTitleAdmin(admin.ModelAdmin):
    list_display = ("title", "media_type", "tmdb_id", "vote_average", "popularity", "last_synced")
    search_fields = ("title", "original_title", "tmdb_id")
    list_filter = ("media_type", "original_language")
    readonly_fields = ("last_synced",)
@admin.register(WatchlistItem)
class WatchlistItemAdmin(admin.ModelAdmin):
    list_display = ("user", "catalog_title", "added_at")
    search_fields = ("user__username", "catalog_title__title")
@admin.register(PlaybackProgress)
class PlaybackProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "catalog_title", "timestamp", "is_finished", "last_watched")
@admin.register(TransientStreamSession)
class TransientStreamSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "created_at", "expires_at")
    readonly_fields = ("magnet_uri",)
admin.site.register(UserProfile)
