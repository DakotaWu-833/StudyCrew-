"""Top-level URL routing for StudyCrew."""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from config import views as error_views


urlpatterns = [
    path("", include("web.urls")),
    path("account/", include("accounts.urls")),
    path("api/v1/", include("api.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
]

handler400 = error_views.bad_request
handler403 = error_views.permission_denied
handler404 = error_views.not_found
handler500 = error_views.server_error
