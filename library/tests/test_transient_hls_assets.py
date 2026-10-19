import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from library.models import TransientStreamSession


class TransientHLSAssetTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.override = override_settings(TRANSIENT_STREAM_ROOT=Path(self.temp.name))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.temp.cleanup)
        self.user = User.objects.create_user(username='hls-owner', password='test-password')
        self.other = User.objects.create_user(username='hls-other', password='test-password')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.session = TransientStreamSession.objects.create(user=self.user, magnet_uri='', status='ACTIVE', expires_at=timezone.now() + timedelta(minutes=30))
        self.directory = Path(self.temp.name) / str(self.session.pk)
        self.directory.mkdir()
        (self.directory / 'index.m3u8').write_text('#EXTM3U\n#EXTINF:4.0,\nsegment_00000.ts\n', encoding='utf-8')
        (self.directory / 'segment_00000.ts').write_bytes(b'test-segment')

    def url(self, asset='index.m3u8'):
        return reverse('transient_stream_hls_asset', kwargs={'session_id': self.session.pk, 'asset_name': asset})

    def test_owner_gets_no_store_playlist(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(b''.join(response.streaming_content), b'#EXTM3U\n#EXTINF:4.0,\nsegment_00000.ts\n')

    def test_owner_can_get_allowlisted_segment(self):
        response = self.client.get(self.url('segment_00000.ts'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'test-segment')

    def test_rejects_unlisted_asset(self):
        self.assertEqual(self.client.get(self.url('private.mp4')).status_code, 404)

    def test_other_user_cannot_read_assets(self):
        self.client.force_authenticate(user=self.other)
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_stopped_session_cannot_serve_assets(self):
        self.session.status = TransientStreamSession.STATUS_STOPPED
        self.session.save(update_fields=['status'])
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_signed_url_works_without_login_and_carries_token_to_segments(self):
        from library.api import TransientHLSAssetAPIView
        from urllib.parse import urlencode

        token = TransientHLSAssetAPIView.make_token(self.session)
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url() + "?" + urlencode({"token": token}))
        self.assertEqual(response.status_code, 200)
        playlist = b"".join(response.streaming_content).decode("utf-8")
        self.assertIn("segment_00000.ts?token=", playlist)
