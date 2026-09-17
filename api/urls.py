from django.urls import path
from rest_framework.routers import SimpleRouter

from api.views import (
    CommentViewSet,
    ExportViewSet,
    HealthView,
    InvitationViewSet,
    MeetingViewSet,
    MembershipViewSet,
    NotificationViewSet,
    ProfileView,
    ProjectViewSet,
    TaskViewSet,
    me_view,
)


app_name = "api"

router = SimpleRouter(use_regex_path=False)
router.register("projects", ProjectViewSet, basename="project")
router.register("tasks", TaskViewSet, basename="task")
router.register("comments", CommentViewSet, basename="comment")
router.register("meetings", MeetingViewSet, basename="meeting")
router.register("invitations", InvitationViewSet, basename="invitation")
router.register("memberships", MembershipViewSet, basename="membership")
router.register("notifications", NotificationViewSet, basename="notification")
router.register("exports", ExportViewSet, basename="export")

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("me/", me_view, name="me"),
    path("profile/", ProfileView.as_view(), name="profile"),
    *router.urls,
]
