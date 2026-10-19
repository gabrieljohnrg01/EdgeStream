from django.db import migrations, models
import django.db.models.deletion

def discard_legacy_media_progress(apps, schema_editor):
    apps.get_model("library", "WatchlistItem").objects.all().delete()
    apps.get_model("library", "PlaybackProgress").objects.all().delete()

class Migration(migrations.Migration):
    dependencies = [("library", "0015_catalogtitle")]
    operations = [
        migrations.RunPython(discard_legacy_media_progress, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(name="playbackprogress", unique_together=set()),
        migrations.RemoveField(model_name="watchlistitem", name="movie"),
        migrations.RemoveField(model_name="watchlistitem", name="series"),
        migrations.RemoveField(model_name="playbackprogress", name="movie"),
        migrations.RemoveField(model_name="playbackprogress", name="episode"),
        migrations.DeleteModel(name="ConversionTask"),
        migrations.DeleteModel(name="MediaItem"),
        migrations.DeleteModel(name="Episode"),
        migrations.DeleteModel(name="Season"),
        migrations.DeleteModel(name="Movie"),
        migrations.DeleteModel(name="Series"),
        migrations.DeleteModel(name="Genre"),
        migrations.AddField(model_name="watchlistitem", name="catalog_title", field=models.ForeignKey(to="library.catalogtitle", on_delete=django.db.models.deletion.CASCADE, related_name="watchlist_items")),
        migrations.AddConstraint(model_name="watchlistitem", constraint=models.UniqueConstraint(fields=("user", "catalog_title"), name="unique_user_catalog_watchlist")),
        migrations.AddField(model_name="playbackprogress", name="catalog_title", field=models.ForeignKey(to="library.catalogtitle", on_delete=django.db.models.deletion.CASCADE, related_name="playback_progress")),
        migrations.AddConstraint(model_name="playbackprogress", constraint=models.UniqueConstraint(fields=("user", "catalog_title"), name="unique_user_catalog_progress")),
    ]
