import re
import subprocess
import sys
from datetime import timedelta
from urllib.parse import urlencode
from django.conf import settings
from django.core import signing
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from rest_framework import generics, status, viewsets, filters
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from .models import CatalogTitle, WatchlistItem, PlaybackProgress, TransientStreamSession
from .serializers import CatalogTitleSerializer, WatchlistItemSerializer, UserRegistrationSerializer, ChangePasswordSerializer
from .transient_streaming import validate_magnet_uri
from .transient_streaming_runtime import resolve_hls_asset, session_output_dir

class CatalogTitleViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = CatalogTitleSerializer
    queryset = CatalogTitle.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "original_title", "overview"]
    ordering_fields = ["popularity", "vote_average", "release_date", "title"]
    ordering = ["-popularity", "title"]
    def get_queryset(self):
        queryset = super().get_queryset()
        media_type = self.request.query_params.get("media_type")
        if media_type in (CatalogTitle.MEDIA_MOVIE, CatalogTitle.MEDIA_TV):
            queryset = queryset.filter(media_type=media_type)
        return queryset

class WatchlistViewSet(viewsets.ModelViewSet):
    serializer_class = WatchlistItemSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]
    def get_queryset(self):
        return WatchlistItem.objects.filter(user=self.request.user).select_related("catalog_title")
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class RegisterUserAPIView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)}, status=status.HTTP_201_CREATED)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            if user.check_password(serializer.data.get("old_password")):
                user.set_password(serializer.data.get("new_password"))
                user.save()
                return Response({"message": "Password updated successfully."})
            return Response({"old_password": ["Wrong password."]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CatalogProgressAPIView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        rows = PlaybackProgress.objects.filter(user=request.user).select_related("catalog_title")
        return Response([{"tmdb_id": x.catalog_title.tmdb_id, "media_type": x.catalog_title.media_type, "timestamp": x.timestamp, "is_finished": x.is_finished, "last_watched": x.last_watched} for x in rows])
    def post(self, request):
        try:
            tmdb_id = int(request.data.get("tmdb_id"))
            media_type = str(request.data.get("media_type", "")).upper()
            timestamp = max(0, int(request.data.get("timestamp", 0)))
        except (TypeError, ValueError):
            return Response({"detail": "Provide valid tmdb_id, media_type, and timestamp."}, status=400)
        if media_type not in (CatalogTitle.MEDIA_MOVIE, CatalogTitle.MEDIA_TV):
            return Response({"detail": "media_type must be MOVIE or TV."}, status=400)
        title = get_object_or_404(CatalogTitle, tmdb_id=tmdb_id, media_type=media_type)
        row, _ = PlaybackProgress.objects.update_or_create(user=request.user, catalog_title=title, defaults={"timestamp": timestamp, "is_finished": bool(request.data.get("is_finished", False))})
        return Response({"tmdb_id": title.tmdb_id, "media_type": title.media_type, "timestamp": row.timestamp, "is_finished": row.is_finished})

def expire_transient_sessions(queryset=None):
    """Expire stale session metadata without touching filesystem paths."""
    now = timezone.now()
    sessions = queryset if queryset is not None else TransientStreamSession.objects.all()
    active_statuses = [
        TransientStreamSession.STATUS_PENDING,
        TransientStreamSession.STATUS_STARTING,
        TransientStreamSession.STATUS_ACTIVE,
    ]
    sessions.filter(expires_at__lte=now, status__in=active_statuses).update(
        status=TransientStreamSession.STATUS_STOPPED,
        stopped_at=now,
        magnet_uri="",
        selected_file="",
    )
    sessions.filter(expires_at__lte=now, status=TransientStreamSession.STATUS_STOPPED).exclude(
        magnet_uri=""
    ).update(magnet_uri="", selected_file="")

class RegisterUserAPIView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }, status=status.HTTP_201_CREATED)


class MovieViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Movie.objects.filter(is_converted=True).prefetch_related('genres')
    serializer_class = MovieSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['title', 'description']

class SeriesViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Series.objects.filter(seasons__episodes__is_converted=True).distinct().prefetch_related('genres', 'seasons__episodes')
    serializer_class = SeriesSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['title', 'description']

class SeasonViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Season.objects.filter(episodes__is_converted=True).distinct()
    serializer_class = SeasonSerializer

class EpisodeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Episode.objects.filter(is_converted=True)
    serializer_class = EpisodeSerializer

class WatchlistViewSet(viewsets.ModelViewSet):
    serializer_class = WatchlistItemSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return WatchlistItem.objects.filter(user=self.request.user).select_related('movie', 'series')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = ChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            if user.check_password(serializer.data.get("old_password")):
                user.set_password(serializer.data.get("new_password"))
                user.save()
                return Response({"message": "Password updated successfully."}, status=status.HTTP_200_OK)
            return Response({"old_password": ["Wrong password."]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



class TransientStreamSessionListCreateAPIView(APIView):
    """Owner-scoped session metadata API; no torrent worker is launched by this endpoint yet."""
    permission_classes = [IsAuthenticated]
    MAX_ACTIVE_SESSIONS = 2
    SESSION_TTL = timedelta(hours=3)

    def get(self, request):
        expire_transient_sessions(TransientStreamSession.objects.filter(user=request.user))
        sessions = TransientStreamSession.objects.filter(user=request.user).order_by("-created_at")[:50]
        return Response([self.serialize_session(session) for session in sessions])

    def post(self, request):
        magnet_uri = request.data.get("magnet_uri", "")
        try:
            magnet_uri = validate_magnet_uri(magnet_uri)
        except (TypeError, ValueError):
            return Response(
                {"detail": "Provide a valid magnet URI containing a BitTorrent info hash."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        expire_transient_sessions(TransientStreamSession.objects.filter(user=request.user))
        active_statuses = [
            TransientStreamSession.STATUS_PENDING,
            TransientStreamSession.STATUS_STARTING,
            TransientStreamSession.STATUS_ACTIVE,
        ]

        active_count = TransientStreamSession.objects.filter(
            user=request.user, status__in=active_statuses, expires_at__gt=now
        ).count()
        if active_count >= self.MAX_ACTIVE_SESSIONS:
            return Response(
                {"detail": "You have reached the limit of 2 active transient sessions."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        session = TransientStreamSession.objects.create(
            user=request.user,
            magnet_uri=magnet_uri,
            expires_at=now + self.SESSION_TTL,
            status=TransientStreamSession.STATUS_PENDING,
        )
        worker_started = False
        if getattr(settings, "TRANSIENT_STREAM_WORKERS_ENABLED", False):
            try:
                worker_dir = session_output_dir(session.pk)
                worker_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
                log_path = worker_dir / "worker.log"
                with open(log_path, "ab") as worker_log:
                    subprocess.Popen(
                        [
                            sys.executable,
                            str(settings.BASE_DIR / "manage.py"),
                            "download_transient_torrent",
                            str(session.pk),
                        ],
                        cwd=str(settings.BASE_DIR),
                        stdin=subprocess.DEVNULL,
                        stdout=worker_log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                        close_fds=True,
                    )
                session.status = TransientStreamSession.STATUS_STARTING
                session.save(update_fields=["status"])
                worker_started = True
            except OSError:
                session.status = TransientStreamSession.STATUS_FAILED
                session.last_error = "Could not start the transient worker process."
                session.magnet_uri = ""
                session.save(update_fields=["status", "last_error", "magnet_uri"])

        detail = (
            "Worker started. Playback becomes available when the selected file is downloaded and HLS output is ready."
            if worker_started else
            "Session created but worker autostart is disabled. Enable TRANSIENT_STREAM_WORKERS_ENABLED and install FFmpeg plus Python libtorrent on the backend host."
        )
        return Response({
            **self.serialize_session(session),
            "playback_ready": False,
            "worker_started": worker_started,
            "detail": detail,
        }, status=status.HTTP_201_CREATED)

    @staticmethod
    def serialize_session(session):
        # Never return the magnet URI or private worker error details.
        return {
            "id": str(session.pk),
            "status": session.status,
            "selected_file": session.selected_file,
            "created_at": session.created_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "stopped_at": session.stopped_at.isoformat() if session.stopped_at else None,
        }


class TransientStreamSessionDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, request, session_id):
        try:
            return TransientStreamSession.objects.get(pk=session_id, user=request.user)
        except (TransientStreamSession.DoesNotExist, ValueError):
            return None

    def get(self, request, session_id):
        expire_transient_sessions(TransientStreamSession.objects.filter(user=request.user))
        session = self.get_object(request, session_id)
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        payload = TransientStreamSessionListCreateAPIView.serialize_session(session)
        payload["playback_ready"] = False
        if session.status == TransientStreamSession.STATUS_ACTIVE:
            token = TransientHLSAssetAPIView.make_token(session)
            asset_path = reverse("transient_stream_hls_asset", kwargs={
                "session_id": session.pk,
                "asset_name": "index.m3u8",
            })
            payload["playback_url"] = f"{asset_path}?{urlencode({'token': token})}"
            payload["playback_ready"] = True
            payload["playback_url_expires_in"] = TransientHLSAssetAPIView.TOKEN_MAX_AGE_SECONDS
        return Response(payload)

    def post(self, request, session_id):
        """Stop a session. Worker process teardown will be wired in with the supervisor."""
        session = self.get_object(request, session_id)
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        if session.status != TransientStreamSession.STATUS_STOPPED:
            session.status = TransientStreamSession.STATUS_STOPPED
            session.stopped_at = timezone.now()
            session.magnet_uri = ""
            session.selected_file = ""
            session.save(update_fields=["status", "stopped_at", "magnet_uri", "selected_file"])
        return Response({"id": str(session.pk), "status": session.status, "playback_ready": False})



class TransientHLSAssetAPIView(APIView):
    """Serve active session HLS files using owner auth or a short-lived signed URL.

    The signed URL is needed because native iOS HLS requests cannot reliably attach
    the application's Bearer token to every playlist and segment request.
    """
    permission_classes = [AllowAny]
    TOKEN_SALT = "library.transient-hls-asset"
    TOKEN_MAX_AGE_SECONDS = 10800

    @classmethod
    def make_token(cls, session):
        return signing.dumps(
            {"session": str(session.pk), "user": session.user_id},
            salt=cls.TOKEN_SALT,
            compress=True,
        )

    def get(self, request, session_id, asset_name):
        now = timezone.now()
        session = TransientStreamSession.objects.filter(
            pk=session_id,
            status=TransientStreamSession.STATUS_ACTIVE,
            expires_at__gt=now,
        ).first()
        if session is None:
            return Response({"detail": "Stream asset not found."}, status=status.HTTP_404_NOT_FOUND)

        authorized = bool(
            getattr(request.user, "is_authenticated", False)
            and request.user.pk == session.user_id
        )
        token = request.query_params.get("token", "")
        if not authorized and token:
            try:
                payload = signing.loads(token, salt=self.TOKEN_SALT, max_age=self.TOKEN_MAX_AGE_SECONDS)
                authorized = payload == {"session": str(session.pk), "user": session.user_id}
            except (signing.BadSignature, signing.SignatureExpired, TypeError, ValueError):
                authorized = False
        if not authorized:
            return Response({"detail": "Stream asset not found."}, status=status.HTTP_404_NOT_FOUND)

        asset = resolve_hls_asset(session.pk, asset_name)
        if asset is None:
            raise Http404("Stream asset not found.")

        if asset.suffix == ".m3u8":
            # Rewrite only allowlisted segment names so the signed token follows each
            # request on browsers and native HLS clients. Never forward arbitrary URIs.
            try:
                playlist = asset.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                raise Http404("Stream asset not found.")
            if len(playlist) > 1_000_000:
                return Response({"detail": "Playlist too large."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            lines = []
            for line in playlist.splitlines():
                item = line.strip()
                if not item or item.startswith("#"):
                    lines.append(line)
                elif re.fullmatch(r"segment_[0-9]{5}\.ts", item):
                    if token:
                        lines.append(f"{item}?token={token}")
                    else:
                        lines.append(item)
                else:
                    # Drop URI references that are outside the supported HLS allowlist.
                    continue
            response = HttpResponse("\n".join(lines) + "\n", content_type="application/vnd.apple.mpegurl")
        else:
            response = FileResponse(open(asset, "rb"), content_type="video/mp2t")
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        response["X-Content-Type-Options"] = "nosniff"
        return response
