from django.urls import include, path
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
    ProfileAvatarView,
    UserAvatarView,
    TimeZonesView,
    EmailChangeStartView,
    EmailChangeConfirmView,
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
    path("account/", include("accounts.readiness_urls")),
    path("campus/", include("campus.urls")),
    path("coordination/", include("coordination.urls")),
    path("operations/", include("operations.urls")),
    path("recruiting/", include("recruiting.urls")),
    path("files/", include("documents_store.urls")),
    path("learning-exchange/", include("learning_exchange.urls")),
    path("chat/", include("project_chat.urls")),
    path("offline/", include("api.offline_urls")),
    path("productivity/", include("productivity.urls")),
    path("health/", HealthView.as_view(), name="health"),
    path("me/", me_view, name="me"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("profile/avatar/", ProfileAvatarView.as_view(), name="profile-avatar"),
    path("users/<uuid:user_id>/avatar/", UserAvatarView.as_view(), name="user-avatar"),
    path("time-zones/", TimeZonesView.as_view(), name="time-zones"),
    path("account/email-change/request/", EmailChangeStartView.as_view(), name="email-change-request"),
    path("account/email-change/confirm/", EmailChangeConfirmView.as_view(), name="email-change-confirm"),
    *router.urls,
]
