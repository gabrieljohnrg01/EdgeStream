# Generated for isolated transient streaming sessions.
import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0013_alter_episode_still_url_alter_movie_backdrop_url_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TransientStreamSession",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("magnet_uri", models.TextField()),
                ("selected_file", models.CharField(blank=True, max_length=1024)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("STARTING", "Starting"), ("ACTIVE", "Active"), ("STOPPED", "Stopped"), ("FAILED", "Failed")], db_index=True, default="PENDING", max_length=16)),
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("stopped_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.CharField(blank=True, max_length=500)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="transient_stream_sessions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="transientstreamsession",
            index=models.Index(fields=["user", "status"], name="library_tr_user_id_0d2e5a_idx"),
        ),
    ]
