import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from library.models import TransientStreamSession


class TransientHLSWorkerSafetyTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.override = override_settings(TRANSIENT_STREAM_ROOT=Path(self.temp.name))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.temp.cleanup)
        self.user = User.objects.create_user(username="worker-owner", password="test-password")
        self.session = TransientStreamSession.objects.create(
            user=self.user,
            magnet_uri="",
            status=TransientStreamSession.STATUS_PENDING,
            expires_at=timezone.now() + timedelta(minutes=30),
        )

    def test_worker_rejects_path_traversal_before_running_ffmpeg(self):
        with self.assertRaises(CommandError):
            call_command("run_transient_hls", str(self.session.pk), source="../outside.mkv")
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, TransientStreamSession.STATUS_PENDING)

    def test_worker_rejects_non_pending_session(self):
        self.session.status = TransientStreamSession.STATUS_STOPPED
        self.session.save(update_fields=["status"])
        with self.assertRaises(CommandError):
            call_command("run_transient_hls", str(self.session.pk), source="download/movie.mkv")
