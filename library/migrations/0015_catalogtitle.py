# TMDB catalog is separate from local file-backed Movie and Episode models.
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0014_transient_stream_session"),
    ]

    operations = [
        migrations.CreateModel(
            name="CatalogTitle",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tmdb_id", models.PositiveIntegerField()),
                ("media_type", models.CharField(choices=[("MOVIE", "Movie"), ("TV", "TV Show")], max_length=8)),
                ("title", models.CharField(db_index=True, max_length=255)),
                ("original_title", models.CharField(blank=True, max_length=255)),
                ("overview", models.TextField(blank=True)),
                ("poster_path", models.CharField(blank=True, max_length=255)),
                ("backdrop_path", models.CharField(blank=True, max_length=255)),
                ("release_date", models.DateField(blank=True, null=True)),
                ("original_language", models.CharField(blank=True, max_length=12)),
                ("vote_average", models.FloatField(default=0)),
                ("vote_count", models.PositiveIntegerField(default=0)),
                ("popularity", models.FloatField(default=0)),
                ("genre_ids", models.JSONField(blank=True, default=list)),
                ("sections", models.JSONField(blank=True, default=list)),
                ("last_synced", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
            ],
            options={"ordering": ["-popularity", "title"]},
        ),
        migrations.AddConstraint(
            model_name="catalogtitle",
            constraint=models.UniqueConstraint(fields=("media_type", "tmdb_id"), name="unique_catalog_media_tmdb_id"),
        ),
        migrations.AddIndex(
            model_name="catalogtitle",
            index=models.Index(fields=["media_type", "-popularity"], name="catalog_media_pop_idx"),
        ),
        migrations.AddIndex(
            model_name="catalogtitle",
            index=models.Index(fields=["media_type", "vote_average"], name="catalog_media_vote_idx"),
        ),
    ]
