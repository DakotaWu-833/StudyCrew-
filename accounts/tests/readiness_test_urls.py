from django.urls import include, path

urlpatterns = [
    path("api/v1/account/", include("accounts.readiness_urls")),
    path("", include("config.urls")),
]
