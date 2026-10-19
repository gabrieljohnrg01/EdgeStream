from django.urls import path
from . import views
urlpatterns = [
 path("", views.index, name="index"),
 path("catalog/", views.tmdb_catalog_view, name="tmdb_catalog"),
 path("movies/", views.tmdb_catalog_view, name="movies"),
 path("series/", views.tmdb_catalog_view, name="series"),
 path("search/", views.search, name="search"),
 path("transient-streams/", views.transient_streams_view, name="transient_streams"),
 path("transient-streams/<uuid:session_id>/play/", views.transient_stream_playback, name="transient_stream_playback"),
 path("register/", views.register_view, name="register"),
 path("login/", views.login_view, name="login"),
 path("logout/", views.logout_view, name="logout"),
 path("watchlist/", views.watchlist_view, name="watchlist"),
 path("ajax/watchlist/toggle/", views.api_toggle_watchlist, name="api_toggle_watchlist"),
 path("api/progress/update/", views.api_update_progress, name="api_update_progress"),
 path("api/profile/me/", views.api_my_profile, name="api_my_profile"),
 path("settings/", views.settings_view, name="settings"),
]
