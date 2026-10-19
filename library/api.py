from datetime import timedelta

from django.utils import timezone
from rest_framework import viewsets, generics, status, filters
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from .models import Movie, Series, Season, Episode, WatchlistItem, TransientStreamSession
from .serializers import MovieSerializer, SeriesSerializer, SeasonSerializer, EpisodeSerializer, UserRegistrationSerializer, WatchlistItemSerializer, ChangePasswordSerializer
from .transient_streaming import validate_magnet_uri

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
        active_statuses = [
            TransientStreamSession.STATUS_PENDING,
            TransientStreamSession.STATUS_STARTING,
            TransientStreamSession.STATUS_ACTIVE,
        ]
        TransientStreamSession.objects.filter(
            user=request.user,
            expires_at__lte=now,
            status__in=active_statuses,
        ).update(status=TransientStreamSession.STATUS_STOPPED, stopped_at=now, magnet_uri="", selected_file="")

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
        return Response({
            **self.serialize_session(session),
            "playback_ready": False,
            "detail": "Session metadata created. Torrent/FFmpeg worker is not configured yet; this session cannot play media yet.",
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
        session = self.get_object(request, session_id)
        if session is None:
            return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(TransientStreamSessionListCreateAPIView.serialize_session(session))

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
