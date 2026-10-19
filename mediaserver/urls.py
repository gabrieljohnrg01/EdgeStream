from django.urls import include, path
from rest_framework import routers
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from library.api import CatalogTitleViewSet, WatchlistViewSet, RegisterUserAPIView, ChangePasswordView, CatalogProgressAPIView, TransientStreamSessionListCreateAPIView, TransientStreamSessionDetailAPIView, TransientHLSAssetAPIView
from library import views
router = routers.DefaultRouter()
router.register("catalog", CatalogTitleViewSet, basename="catalog")
router.register("watchlist", WatchlistViewSet, basename="watchlist")
urlpatterns = [
 path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
 path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
 path("api/register/", RegisterUserAPIView.as_view(), name="api_register"),
 path("api/change-password/", ChangePasswordView.as_view(), name="change_password"),
 path("api/webview-login/", views.webview_login, name="webview_login"),
 path("api/transient-streams/", TransientStreamSessionListCreateAPIView.as_view(), name="transient_stream_list_create"),
 path("api/transient-streams/<uuid:session_id>/", TransientStreamSessionDetailAPIView.as_view(), name="transient_stream_detail"),
 path("api/transient-streams/<uuid:session_id>/hls/<str:asset_name>", TransientHLSAssetAPIView.as_view(), name="transient_stream_hls_asset"),
 path("api/progress/", CatalogProgressAPIView.as_view(), name="catalog_progress"),
 path("api/", include(router.urls)),
 path("", include("library.urls")),
]
