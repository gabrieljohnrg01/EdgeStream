from pathlib import Path
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from .models import CatalogTitle, PlaybackProgress, TransientStreamSession, UserProfile, WatchlistItem

def webview_login(request):
    token = request.GET.get("token")
    next_url = request.GET.get("next", "/")
    if token:
        try:
            auth = JWTAuthentication()
            user = auth.get_user(auth.get_validated_token(token))
            if user and user.is_active:
                login(request, user)
                return redirect(next_url)
        except (InvalidToken, TokenError):
            pass
    return redirect("login")

def account_select(request):
    return redirect("login")

def index(request):
    return tmdb_catalog_view(request)

def tmdb_catalog_view(request):
    query = (request.GET.get("q") or "").strip()[:100]
    media_type = request.GET.get("type", "ALL").upper()
    section = request.GET.get("section", "trending")
    sections = {"trending": ("trending_movies", "trending_tv"), "popular": ("popular_movies", "popular_tv"), "top_rated": ("top_rated_movies", "top_rated_tv"), "upcoming": ("upcoming_movies",)}
    if section not in sections:
        section = "trending"
    titles = CatalogTitle.objects.all()
    if media_type in (CatalogTitle.MEDIA_MOVIE, CatalogTitle.MEDIA_TV):
        titles = titles.filter(media_type=media_type)
    if query:
        from django.db.models import Q
        titles = titles.filter(Q(title__icontains=query) | Q(original_title__icontains=query) | Q(overview__icontains=query))
    else:
        wanted = sections[section]
        titles = [item for item in titles if any(s in (item.sections or []) for s in wanted)]
    titles = list(titles[:120])
    saved = set(WatchlistItem.objects.filter(user=request.user, catalog_title__in=titles).values_list("catalog_title_id", flat=True)) if request.user.is_authenticated else set()
    for item in titles:
        item.in_watchlist = item.pk in saved
    return render(request, "library/tmdb_catalog.html", {"catalog_titles": titles, "catalog_query": query, "catalog_type": media_type, "catalog_section": section, "catalog_section_choices": [("trending", "Trending"), ("popular", "Popular"), ("top_rated", "Top Rated"), ("upcoming", "Upcoming")]})

def search(request):
    query = (request.GET.get("q") or "").strip()[:100]
    from django.db.models import Q
    titles = CatalogTitle.objects.filter(Q(title__icontains=query) | Q(original_title__icontains=query) | Q(overview__icontains=query))[:120] if query else []
    return render(request, "library/tmdb_catalog.html", {"catalog_titles": titles, "catalog_query": query, "catalog_type": "ALL", "catalog_section": "", "catalog_section_choices": []})

@login_required
def watchlist_view(request):
    return render(request, "library/watchlist.html", {"items": WatchlistItem.objects.filter(user=request.user).select_related("catalog_title")})

@login_required
def api_toggle_watchlist(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    import json
    try:
        payload = json.loads(request.body or "{}")
        title = get_object_or_404(CatalogTitle, pk=int(payload.get("id")))
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"status": "error", "message": "Invalid catalog title"}, status=400)
    item = WatchlistItem.objects.filter(user=request.user, catalog_title=title).first()
    if item:
        item.delete()
        added = False
    else:
        WatchlistItem.objects.get_or_create(user=request.user, catalog_title=title)
        added = True
    return JsonResponse({"status": "success", "added": added})

@login_required
def api_update_progress(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST required"}, status=405)
    import json
    try:
        payload = json.loads(request.body or "{}")
        title = get_object_or_404(CatalogTitle, tmdb_id=int(payload["tmdb_id"]), media_type=str(payload["media_type"]).upper())
        timestamp = max(0, int(payload.get("timestamp", 0)))
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({"status": "error", "message": "Invalid progress payload"}, status=400)
    PlaybackProgress.objects.update_or_create(user=request.user, catalog_title=title, defaults={"timestamp": timestamp, "is_finished": bool(payload.get("is_finished", False))})
    return JsonResponse({"status": "success"})

def transient_streams_view(request):
    if not request.user.is_authenticated:
        return redirect("login")
    sessions = TransientStreamSession.objects.filter(user=request.user).order_by("-created_at")[:20]
    return render(request, "library/transient_streams.html", {"sessions": sessions, "session_api_url": reverse("transient_stream_list_create")})

@login_required
def transient_stream_playback(request, session_id):
    from .api import TransientHLSAssetAPIView, expire_transient_sessions
    expire_transient_sessions(TransientStreamSession.objects.filter(user=request.user))
    session = get_object_or_404(TransientStreamSession, pk=session_id, user=request.user)
    if session.status != TransientStreamSession.STATUS_ACTIVE or session.expires_at <= timezone.now():
        return render(request, "library/transient_stream_waiting.html", {"session": session, "back_url": reverse("transient_streams")}, status=409)
    token = TransientHLSAssetAPIView.make_token(session)
    playlist = reverse("transient_stream_hls_asset", kwargs={"session_id": session.pk, "asset_name": "index.m3u8"})
    playback_url = f"{playlist}?token={token}"
    return render(request, "library/transient_playback.html", {"transient_mode": True, "transient_title": Path(session.selected_file).name or "Transient stream", "transient_back_url": reverse("transient_streams"), "transient_playback_url": playback_url, "movie": None, "hls_playlist": playback_url, "fallback_file": "", "fallback_type": "", "subtitles": [], "saved_timestamp": 0})

def register_view(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            UserProfile.objects.get_or_create(user=user)
            login(request, user)
            return redirect("index")
    else:
        form = UserCreationForm()
    return render(request, "library/register.html", {"form": form})

def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            UserProfile.objects.get_or_create(user=user)
            login(request, user)
            return redirect("index")
    else:
        form = AuthenticationForm(request)
    return render(request, "library/login.html", {"form": form})

def logout_view(request):
    logout(request)
    return redirect("login")

@login_required
def settings_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        if "update_profile" in request.POST:
            profile.theme = request.POST.get("theme", "default")
            avatar = request.FILES.get("avatar")
            if avatar:
                profile.avatar = avatar
            profile.save()
            return redirect("settings")
        if "update_password" in request.POST:
            form = PasswordChangeForm(request.user, request.POST)
            if form.is_valid():
                user = form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Your password was successfully updated.")
                return redirect("settings")
            messages.error(request, "Please correct the errors below.")
    else:
        form = PasswordChangeForm(request.user)
    return render(request, "library/settings.html", {"form": form, "profile": profile})

@login_required
def api_my_profile(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        theme = request.POST.get("theme")
        if theme:
            profile.theme = theme
        avatar = request.FILES.get("avatar")
        if avatar:
            profile.avatar = avatar
        profile.save()
    return JsonResponse({"username": request.user.username, "avatar": profile.avatar.url if profile.avatar else None, "theme": profile.theme})
