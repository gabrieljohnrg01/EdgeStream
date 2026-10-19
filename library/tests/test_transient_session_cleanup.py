from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from library.models import TransientStreamSession


class TransientStreamSessionCleanupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="stream-test", password="not-used")

    def create_session(self, *, expires_at, status=TransientStreamSession.STATUS_ACTIVE):
        return TransientStreamSession.objects.create(
            user=self.user,
            magnet_uri="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
            expires_at=expires_at,
            status=status,
        )

    def test_cleanup_expires_session_and_scrubs_magnet(self):
        session = self.create_session(expires_at=timezone.now() - timedelta(minutes=1))
        output = StringIO()

        call_command("cleanup_transient_streams", stdout=output)

        session.refresh_from_db()
        self.assertEqual(session.status, TransientStreamSession.STATUS_STOPPED)
        self.assertEqual(session.magnet_uri, "")
        self.assertIn("No media files were deleted", output.getvalue())

    def test_cleanup_leaves_unexpired_session_untouched(self):
        session = self.create_session(expires_at=timezone.now() + timedelta(hours=1))
        call_command("cleanup_transient_streams")
        session.refresh_from_db()
        self.assertEqual(session.status, TransientStreamSession.STATUS_ACTIVE)
        self.assertTrue(session.magnet_uri)
