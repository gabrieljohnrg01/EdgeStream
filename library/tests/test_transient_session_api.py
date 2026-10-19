from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from library.models import TransientStreamSession


MAGNET = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Example"


class TransientSessionAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="session-owner", password="test-password")
        self.other_user = User.objects.create_user(username="other-owner", password="test-password")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_create_requires_valid_magnet_and_does_not_return_it(self):
        url = reverse("transient_stream_list_create")
        invalid = self.client.post(url, {"magnet_uri": "https://example.test/video"}, format="json")
        self.assertEqual(invalid.status_code, 400)

        response = self.client.post(url, {"magnet_uri": MAGNET}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["playback_ready"])
        self.assertNotIn("magnet_uri", response.data)
        self.assertEqual(TransientStreamSession.objects.filter(user=self.user).count(), 1)

    def test_session_limit_is_enforced(self):
        for _ in range(2):
            TransientStreamSession.objects.create(
                user=self.user, magnet_uri=MAGNET, expires_at=timezone.now() + timedelta(hours=1)
            )
        response = self.client.post(reverse("transient_stream_list_create"), {"magnet_uri": MAGNET}, format="json")
        self.assertEqual(response.status_code, 429)

    def test_user_cannot_read_or_stop_another_users_session(self):
        session = TransientStreamSession.objects.create(
            user=self.other_user, magnet_uri=MAGNET, expires_at=timezone.now() + timedelta(hours=1)
        )
        url = reverse("transient_stream_detail", kwargs={"session_id": session.pk})
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)
        session.refresh_from_db()
        self.assertEqual(session.status, TransientStreamSession.STATUS_PENDING)

    def test_stop_scrubs_private_magnet_metadata(self):
        session = TransientStreamSession.objects.create(
            user=self.user, magnet_uri=MAGNET, expires_at=timezone.now() + timedelta(hours=1)
        )
        url = reverse("transient_stream_detail", kwargs={"session_id": session.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.status, TransientStreamSession.STATUS_STOPPED)
        self.assertEqual(session.magnet_uri, "")

    def test_api_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(reverse("transient_stream_list_create"), {"magnet_uri": MAGNET}, format="json")
        self.assertEqual(response.status_code, 401)
