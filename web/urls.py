from django.urls import path

from web import views

app_name = "web"

urlpatterns = [
    path("", views.home, name="home"),
    path("app/", views.dashboard, name="dashboard"),
    path("app/<path:route>/", views.dashboard, name="app_route"),
    path("control/", views.control_dashboard, name="control_dashboard"),
    path(
        "control/users/<uuid:user_id>/status/",
        views.control_user_status,
        name="control_user_status",
    ),
    path(
        "control/reports/<uuid:report_id>/resolve/",
        views.control_report_resolution,
        name="control_report_resolution",
    ),
]
