import uuid
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    theme = models.CharField(max_length=50, default="default")
    def __str__(self):
        return f"{self.user.username}'s profile"

class CatalogTitle(models.Model):
    """TMDB metadata only; no permanent video-file or HLS paths."""
    MEDIA_MOVIE = "MOVIE"
    MEDIA_TV = "TV"
    MEDIA_CHOICES = [(MEDIA_MOVIE, "Movie"), (MEDIA_TV, "TV Show")]
    tmdb_id = models.PositiveIntegerField()
    media_type = models.CharField(max_length=8, choices=MEDIA_CHOICES)
    title = models.CharField(max_length=255, db_index=True)
    original_title = models.CharField(max_length=255, blank=True)
    overview = models.TextField(blank=True)
    poster_path = models.CharField(max_length=255, blank=True)
    backdrop_path = models.CharField(max_length=255, blank=True)
    release_date = models.DateField(null=True, blank=True)
    original_language = models.CharField(max_length=12, blank=True)
    vote_average = models.FloatField(default=0)
    vote_count = models.PositiveIntegerField(default=0)
    popularity = models.FloatField(default=0)
    genre_ids = models.JSONField(default=list, blank=True)
    sections = models.JSONField(default=list, blank=True)
    last_synced = models.DateTimeField(default=timezone.now, db_index=True)
    class Meta:
        ordering = ["-popularity", "title"]
        constraints = [models.UniqueConstraint(fields=["media_type", "tmdb_id"], name="unique_catalog_media_tmdb_id")]
        indexes = [models.Index(fields=["media_type", "-popularity"], name="catalog_media_pop_idx"), models.Index(fields=["media_type", "vote_average"], name="catalog_media_vote_idx")]
    @property
    def poster_url(self):
        return f"https://image.tmdb.org/t/p/w500{self.poster_path}" if self.poster_path else ""
    @property
    def backdrop_url(self):
        return f"https://image.tmdb.org/t/p/w1280{self.backdrop_path}" if self.backdrop_path else ""
    def __str__(self):
        return f"{self.title} ({self.media_type}, TMDB {self.tmdb_id})"

class WatchlistItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="watchlist")
    catalog_title = models.ForeignKey(CatalogTitle, on_delete=models.CASCADE, related_name="watchlist_items")
    added_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-added_at"]
        constraints = [models.UniqueConstraint(fields=["user", "catalog_title"], name="unique_user_catalog_watchlist")]
    def __str__(self):
        return f"{self.user.username} - {self.catalog_title.title}"

class PlaybackProgress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="progress")
    catalog_title = models.ForeignKey(CatalogTitle, on_delete=models.CASCADE, related_name="playback_progress")
    timestamp = models.IntegerField(default=0)
    last_watched = models.DateTimeField(auto_now=True)
    is_finished = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "catalog_title"], name="unique_user_catalog_progress")]
    def __str__(self):
        return f"{self.user.username} - {self.catalog_title.title} ({self.timestamp}s)"

class TransientStreamSession(models.Model):
    """User-owned expiring torrent-to-HLS session, separate from the TMDB catalog."""
    STATUS_PENDING = "PENDING"
    STATUS_STARTING = "STARTING"
    STATUS_ACTIVE = "ACTIVE"
    STATUS_STOPPED = "STOPPED"
    STATUS_FAILED = "FAILED"
    STATUS_CHOICES = [(STATUS_PENDING, "Pending"), (STATUS_STARTING, "Starting"), (STATUS_ACTIVE, "Active"), (STATUS_STOPPED, "Stopped"), (STATUS_FAILED, "Failed")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transient_stream_sessions")
    magnet_uri = models.TextField()
    selected_file = models.CharField(max_length=1024, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    stopped_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "status"])]
    def __str__(self):
        return f"Transient stream {self.pk} ({self.status})"
