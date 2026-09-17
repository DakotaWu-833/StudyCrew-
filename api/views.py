"""Thin REST views over authorised selectors and transactional services."""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection
from django.db.models import Prefetch
from django.http import FileResponse
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Profile
from accounts.policies import is_site_moderator
from activity.exports import export_file_for_user, request_export
from activity.insights import contribution_insights
from activity.models import ExportJob
from activity.selectors import events_for_project, notifications_for_user
from activity.services import mark_notification_read
from api.serializers import (
    ActivityEventSerializer,
    AssigneeUpdateSerializer,
    CommentCreateSerializer,
    CommentListQuerySerializer,
    CommentReportSerializer,
    CommentReportResultSerializer,
    CommentSerializer,
    CommentWriteSerializer,
    ExportJobSerializer,
    ExportRequestSerializer,
    HealthSerializer,
    HolidayAdvisorySerializer,
    InsightsQuerySerializer,
    InsightsResponseSerializer,
    InvitationDispatchSerializer,
    InvitationListQuerySerializer,
    InvitationSerializer,
    MeetingCreateSerializer,
    MeetingListQuerySerializer,
    MeetingReplaceSerializer,
    MeetingSerializer,
    MeetingWriteSerializer,
    MeSerializer,
    MembershipListQuerySerializer,
    MembershipRoleUpdateSerializer,
    MembershipSerializer,
    NotificationListQuerySerializer,
    NotificationSerializer,
    OwnershipTransferSerializer,
    ProfileReplaceSerializer,
    ProfileSerializer,
    ProjectListQuerySerializer,
    ProjectReplaceSerializer,
    ProjectSerializer,
    RSVPSerializer,
    TaskCreateSerializer,
    TaskListQuerySerializer,
    TaskReplaceSerializer,
    TaskSerializer,
    TaskTransitionSerializer,
    TaskWriteSerializer,
    UserSummarySerializer,
)
from meetings.models import Meeting
from meetings.selectors import meeting_holiday_advisory, meetings_for_project
from meetings.services import cancel_meeting, create_meeting, set_rsvp, update_meeting
from projects.models import Project, ProjectInvitation, ProjectMembership
from projects.policies import require_project_member, require_project_owner
from projects.selectors import pending_invitations_for_user, projects_for_user
from projects.services import (
    accept_invitation_by_id,
    archive_project,
    cancel_invitation,
    change_member_role,
    create_project,
    decline_invitation_by_id,
    remove_member,
    transfer_ownership,
    update_project,
)
from projects.workflows import create_and_deliver_invitation
from tasks.models import Task, TaskComment
from tasks.policies import active_membership
from tasks.selectors import comment_for_member, task_for_member, tasks_for_project
from tasks.services import (
    archive_task,
    create_comment,
    create_task,
    delete_comment,
    replace_assignees,
    report_comment,
    transition_task,
    update_comment,
    update_task,
)


class UUIDLookupMixin:
    lookup_value_converter = "uuid"


def _validated_query(request, serializer_class):
    serializer = serializer_class(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses=HealthSerializer, auth=[])
    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return Response({"status": "ok", "database": "ok"})


@extend_schema(responses=MeSerializer)
@api_view(["GET"])
def me_view(request):
    profile = get_object_or_404(Profile.objects.select_related("user"), user=request.user)
    return Response(
        {
            "user": UserSummarySerializer(request.user).data,
            "email": request.user.email,
            "profile": ProfileSerializer(profile).data,
            "permissions": {
                "site_moderator": is_site_moderator(request.user)
            },
        }
    )


class ProfileView(APIView):
    serializer_class = ProfileSerializer

    @extend_schema(responses=ProfileSerializer)
    def get(self, request):
        return Response(ProfileSerializer(request.user.profile).data)

    @extend_schema(request=ProfileSerializer, responses=ProfileSerializer)
    def patch(self, request):
        serializer = ProfileSerializer(request.user.profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        return Response(ProfileSerializer(profile).data)

    @extend_schema(request=ProfileReplaceSerializer, responses=ProfileSerializer)
    def put(self, request):
        serializer = ProfileReplaceSerializer(request.user.profile, data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        return Response(ProfileSerializer(profile).data)


@extend_schema_view(
    list=extend_schema(summary="List current projects", parameters=[ProjectListQuerySerializer]),
    create=extend_schema(summary="Create a project and owner membership"),
    update=extend_schema(request=ProjectReplaceSerializer, responses=ProjectSerializer),
    partial_update=extend_schema(request=ProjectSerializer, responses=ProjectSerializer),
    destroy=extend_schema(summary="Soft-archive a project"),
)
class ProjectViewSet(UUIDLookupMixin, viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        return ProjectReplaceSerializer if self.action == "update" else ProjectSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Project.objects.none()
        query = _validated_query(self.request, ProjectListQuerySerializer)
        scope = query["scope"]
        active_memberships = ProjectMembership.objects.active().select_related("user", "user__profile")
        queryset = (
            projects_for_user(self.request.user, include_archived=scope != "active")
            .select_related("created_by", "created_by__profile")
            .prefetch_related(
                Prefetch("memberships", queryset=active_memberships, to_attr="_active_memberships")
            )
        )
        return queryset.filter(archived_at__isnull=False) if scope == "archived" else queryset

    def get_object(self):
        project = get_object_or_404(
            Project.objects.select_related("created_by", "created_by__profile"),
            pk=self.kwargs["pk"],
        )
        require_project_member(self.request.user, project)
        return project

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        project = create_project(
            actor=request.user,
            name=data["name"],
            description=data.get("description", ""),
            due_at=data.get("due_at"),
        )
        return Response(self.get_serializer(project).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        project = self.get_object()
        serializer = self.get_serializer(project, data=request.data, partial=kwargs.get("partial", False))
        serializer.is_valid(raise_exception=True)
        updated = update_project(project=project, actor=request.user, data=serializer.validated_data)
        return Response(self.get_serializer(updated).data)

    def destroy(self, request, *args, **kwargs):
        archive_project(project=self.get_object(), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses=ActivityEventSerializer(many=True))
    @action(detail=True, methods=["get"])
    def activity(self, request, pk=None):
        project = self.get_object()
        queryset = events_for_project(user=request.user, project=project)
        page = self.paginate_queryset(queryset)
        serializer = ActivityEventSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        parameters=[InsightsQuerySerializer],
        responses=InsightsResponseSerializer,
    )
    @action(detail=True, methods=["get"])
    def insights(self, request, pk=None):
        project = self.get_object()
        local_today = timezone.localdate(
            timezone.now(),
            ZoneInfo(request.user.profile.time_zone),
        )
        defaults = {
            "range_start": (local_today - timedelta(days=30)).isoformat(),
            "range_end": local_today.isoformat(),
        }
        query_data = {**defaults, **request.query_params.dict()}
        query = InsightsQuerySerializer(data=query_data)
        query.is_valid(raise_exception=True)
        result = contribution_insights(user=request.user, project=project, **query.validated_data)
        events_with_sentinel = list(result.pop("events")[:201])
        events = events_with_sentinel[:200]
        members = result.pop("members")
        payload = {
            **result,
            "members": [{**row, "user_id": str(row["user_id"])} for row in members],
            "events": ActivityEventSerializer(events, many=True).data,
            "events_truncated": len(events_with_sentinel) > 200,
        }
        return Response(payload)


@extend_schema_view(
    list=extend_schema(parameters=[TaskListQuerySerializer]),
    create=extend_schema(
        request=TaskCreateSerializer,
        responses={status.HTTP_201_CREATED: TaskSerializer},
    ),
    update=extend_schema(request=TaskReplaceSerializer, responses=TaskSerializer),
    partial_update=extend_schema(request=TaskWriteSerializer, responses=TaskSerializer),
)
class TaskViewSet(UUIDLookupMixin, viewsets.ModelViewSet):
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return TaskCreateSerializer
        if self.action == "update":
            return TaskReplaceSerializer
        if self.action == "partial_update":
            return TaskWriteSerializer
        return TaskSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Task.objects.none()
        query = _validated_query(self.request, TaskListQuerySerializer)
        project = get_object_or_404(Project, pk=query["project"])
        scope = query["scope"]
        queryset = tasks_for_project(
            project=project,
            user=self.request.user,
            include_archived=scope != "active",
            query=query.get("q", ""),
            status=query.get("status", ""),
            priority=query.get("priority", ""),
            assignee_id=query.get("assignee"),
            due=query.get("due", ""),
        )
        return queryset.filter(archived_at__isnull=False) if scope == "archived" else queryset

    def get_object(self):
        return task_for_member(
            task_id=self.kwargs["pk"], user=self.request.user, include_archived=True
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        project = data.pop("project")
        task = create_task(project=project, actor=request.user, data=data)
        return Response(TaskSerializer(task, context=self.get_serializer_context()).data, status=201)

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, partial=kwargs.get("partial", False))
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("project", None)
        task = update_task(task=self.get_object(), actor=request.user, data=data)
        return Response(TaskSerializer(task, context=self.get_serializer_context()).data)

    def destroy(self, request, *args, **kwargs):
        archive_task(task=self.get_object(), actor=request.user)
        return Response(status=204)

    @extend_schema(request=AssigneeUpdateSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["put"])
    def assignees(self, request, pk=None):
        serializer = AssigneeUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = replace_assignees(
            task=self.get_object(),
            actor=request.user,
            assignee_ids=serializer.validated_data["assignee_ids"],
        )
        task = task_for_member(task_id=task.id, user=request.user, include_archived=True)
        return Response(TaskSerializer(task, context=self.get_serializer_context()).data)

    @extend_schema(request=TaskTransitionSerializer, responses=TaskSerializer)
    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        serializer = TaskTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = transition_task(
            task=self.get_object(), actor=request.user, **serializer.validated_data
        )
        return Response(TaskSerializer(task, context=self.get_serializer_context()).data)


@extend_schema_view(
    list=extend_schema(parameters=[CommentListQuerySerializer]),
    create=extend_schema(
        request=CommentCreateSerializer,
        responses={status.HTTP_201_CREATED: CommentSerializer},
    ),
    update=extend_schema(request=CommentWriteSerializer, responses=CommentSerializer),
    partial_update=extend_schema(request=CommentWriteSerializer, responses=CommentSerializer),
)
class CommentViewSet(UUIDLookupMixin, viewsets.ModelViewSet):
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return CommentCreateSerializer
        if self.action in {"update", "partial_update"}:
            return CommentWriteSerializer
        return CommentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return TaskComment.objects.none()
        query = _validated_query(self.request, CommentListQuerySerializer)
        task = task_for_member(
            task_id=query["task"],
            user=self.request.user,
            include_archived=True,
        )
        return task.comments.select_related("author", "author__profile").order_by("created_at")

    def get_object(self):
        return comment_for_member(
            comment_id=self.kwargs["pk"], user=self.request.user, include_deleted=True
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        task = data.pop("task")
        comment = create_comment(task=task, actor=request.user, **data)
        return Response(CommentSerializer(comment).data, status=201)

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, partial=kwargs.get("partial", False))
        serializer.is_valid(raise_exception=True)
        if "body" not in serializer.validated_data:
            raise ValidationError({"body": ["This field is required."]})
        comment = update_comment(
            comment=self.get_object(), actor=request.user, body=serializer.validated_data["body"]
        )
        return Response(CommentSerializer(comment).data)

    def destroy(self, request, *args, **kwargs):
        delete_comment(comment=self.get_object(), actor=request.user)
        return Response(status=204)

    @extend_schema(
        request=CommentReportSerializer,
        responses={status.HTTP_201_CREATED: CommentReportResultSerializer},
    )
    @action(detail=True, methods=["post"])
    def report(self, request, pk=None):
        serializer = CommentReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = report_comment(
            comment=self.get_object(), actor=request.user, **serializer.validated_data
        )
        return Response({"id": str(report.id), "status": report.status}, status=201)


@extend_schema_view(
    list=extend_schema(parameters=[MeetingListQuerySerializer]),
    create=extend_schema(
        request=MeetingCreateSerializer,
        responses={status.HTTP_201_CREATED: MeetingSerializer},
    ),
    update=extend_schema(request=MeetingReplaceSerializer, responses=MeetingSerializer),
    partial_update=extend_schema(request=MeetingWriteSerializer, responses=MeetingSerializer),
)
class MeetingViewSet(UUIDLookupMixin, viewsets.ModelViewSet):
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "create":
            return MeetingCreateSerializer
        if self.action == "update":
            return MeetingReplaceSerializer
        if self.action == "partial_update":
            return MeetingWriteSerializer
        return MeetingSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Meeting.objects.none()
        query = _validated_query(self.request, MeetingListQuerySerializer)
        project = get_object_or_404(Project, pk=query["project"])
        return meetings_for_project(project=project, user=self.request.user).prefetch_related("attendances")

    def get_object(self):
        meeting = get_object_or_404(
            Meeting.objects.select_related(
                "project", "organiser", "organiser__profile"
            ).prefetch_related("attendances"),
            pk=self.kwargs["pk"],
        )
        active_membership(project=meeting.project, user=self.request.user)
        return meeting

    def _with_attendance(self, meeting):
        return Meeting.objects.select_related(
            "project", "organiser", "organiser__profile"
        ).prefetch_related("attendances").get(pk=meeting.pk)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        meeting = create_meeting(actor=request.user, **data)
        return Response(
            MeetingSerializer(self._with_attendance(meeting), context=self.get_serializer_context()).data,
            status=201,
        )

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, partial=kwargs.get("partial", False))
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("project", None)
        meeting = update_meeting(meeting=self.get_object(), actor=request.user, **data)
        return Response(
            MeetingSerializer(self._with_attendance(meeting), context=self.get_serializer_context()).data
        )

    def destroy(self, request, *args, **kwargs):
        cancel_meeting(meeting=self.get_object(), actor=request.user)
        return Response(status=204)

    @extend_schema(request=RSVPSerializer, responses=MeetingSerializer)
    @action(detail=True, methods=["put"])
    def rsvp(self, request, pk=None):
        serializer = RSVPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        meeting = self.get_object()
        set_rsvp(meeting=meeting, actor=request.user, **serializer.validated_data)
        return Response(
            MeetingSerializer(self._with_attendance(meeting), context=self.get_serializer_context()).data
        )

    @extend_schema(responses=HolidayAdvisorySerializer)
    @action(detail=True, methods=["get"])
    def holiday(self, request, pk=None):
        return Response(asdict(meeting_holiday_advisory(meeting=self.get_object())))


@extend_schema_view(list=extend_schema(parameters=[InvitationListQuerySerializer]))
class InvitationViewSet(
    UUIDLookupMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = InvitationSerializer

    def get_queryset(self):
        query = _validated_query(self.request, InvitationListQuerySerializer)
        project_id = query.get("project")
        if project_id:
            project = get_object_or_404(Project, pk=project_id)
            require_project_owner(self.request.user, project)
            return project.invitations.select_related("project", "invited_by", "invited_by__profile")
        return pending_invitations_for_user(self.request.user).select_related(
            "project", "invited_by", "invited_by__profile"
        )

    def get_object(self):
        return get_object_or_404(
            ProjectInvitation.objects.select_related("project", "invited_by"),
            pk=self.kwargs["pk"],
        )

    @extend_schema(
        request=InvitationSerializer,
        responses={
            status.HTTP_201_CREATED: InvitationDispatchSerializer,
            status.HTTP_503_SERVICE_UNAVAILABLE: OpenApiResponse(
                description="Email delivery failed and the invitation was rolled back."
            ),
        },
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dispatch = create_and_deliver_invitation(
            actor=request.user,
            project=serializer.validated_data["project"],
            invited_email=serializer.validated_data["invited_email"],
            site_url=request.build_absolute_uri("/"),
        )
        payload = InvitationSerializer(dispatch.invitation).data
        payload["share_token"] = dispatch.token
        return Response(payload, status=201)

    def destroy(self, request, *args, **kwargs):
        cancel_invitation(actor=request.user, invitation=self.get_object())
        return Response(status=204)

    @extend_schema(request=None, responses=ProjectSerializer)
    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        membership = accept_invitation_by_id(actor=request.user, invitation_id=self.kwargs["pk"])
        return Response(ProjectSerializer(membership.project, context={"request": request}).data)

    @extend_schema(request=None, responses=InvitationSerializer)
    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        invitation = decline_invitation_by_id(actor=request.user, invitation_id=self.kwargs["pk"])
        return Response(InvitationSerializer(invitation).data)


@extend_schema_view(
    list=extend_schema(parameters=[MembershipListQuerySerializer]),
    update=extend_schema(request=MembershipRoleUpdateSerializer, responses=MembershipSerializer),
    partial_update=extend_schema(
        request=MembershipRoleUpdateSerializer,
        responses=MembershipSerializer,
    ),
)
class MembershipViewSet(
    UUIDLookupMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = MembershipSerializer
    http_method_names = ["get", "put", "patch", "delete", "post", "head", "options"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ProjectMembership.objects.none()
        query = _validated_query(self.request, MembershipListQuerySerializer)
        project = get_object_or_404(Project, pk=query["project"])
        require_project_member(self.request.user, project)
        return project.memberships.active().select_related("user", "user__profile")

    def get_object(self):
        membership = get_object_or_404(
            ProjectMembership.objects.select_related("project", "user", "user__profile"),
            pk=self.kwargs["pk"],
        )
        require_project_member(self.request.user, membership.project)
        return membership

    def update(self, request, *args, **kwargs):
        membership = self.get_object()
        serializer = MembershipRoleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = change_member_role(
            actor=request.user,
            project=membership.project,
            member=membership.user,
            role=serializer.validated_data["role"],
        )
        return Response(MembershipSerializer(membership).data)

    def destroy(self, request, *args, **kwargs):
        membership = self.get_object()
        remove_member(actor=request.user, project=membership.project, member=membership.user)
        return Response(status=204)

    @extend_schema(request=OwnershipTransferSerializer, responses=MembershipSerializer)
    @action(detail=True, methods=["post"], url_path="transfer-ownership")
    def transfer(self, request, pk=None):
        membership = self.get_object()
        serializer = OwnershipTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        previous_role = serializer.validated_data["previous_owner_role"]
        _previous, incoming = transfer_ownership(
            actor=request.user,
            project=membership.project,
            new_owner=membership.user,
            previous_owner_role=previous_role,
        )
        return Response(self.get_serializer(incoming).data)


@extend_schema_view(list=extend_schema(parameters=[NotificationListQuerySerializer]))
class NotificationViewSet(UUIDLookupMixin, viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        query = _validated_query(self.request, NotificationListQuerySerializer)
        return notifications_for_user(
            self.request.user,
            unread_only=query.get("unread", False),
        )

    @extend_schema(request=None, responses=NotificationSerializer)
    @action(detail=True, methods=["patch"])
    def read(self, request, pk=None):
        notification = mark_notification_read(
            actor=request.user, notification_id=self.kwargs["pk"]
        )
        return Response(self.get_serializer(notification).data)


@extend_schema_view(
    create=extend_schema(
        request=ExportRequestSerializer,
        responses={status.HTTP_201_CREATED: ExportJobSerializer},
    )
)
class ExportViewSet(
    UUIDLookupMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    def get_serializer_class(self):
        return ExportRequestSerializer if self.action == "create" else ExportJobSerializer

    def get_queryset(self):
        return ExportJob.objects.filter(
            requested_by=self.request.user,
            project__memberships__user=self.request.user,
            project__memberships__removed_at__isnull=True,
        ).select_related("project").distinct()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        export_format = data.pop("format")
        job = request_export(actor=request.user, export_format=export_format, **data)
        return Response(ExportJobSerializer(job, context={"request": request}).data, status=201)

    @extend_schema(
        responses={
            (status.HTTP_200_OK, "text/csv"): OpenApiTypes.BINARY,
            (status.HTTP_200_OK, "application/pdf"): OpenApiTypes.BINARY,
        }
    )
    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        job = self.get_object()
        path = export_file_for_user(job=job, user=request.user)
        content_type = "text/csv" if job.format == ExportJob.Format.CSV else "application/pdf"
        filename = f"studycrew-evidence-{job.id}.{job.format}"
        if settings.USE_X_ACCEL_REDIRECT:
            response = HttpResponse(content_type=content_type)
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            response["X-Accel-Redirect"] = f"/protected-media/{quote(job.storage_key, safe='/')}"
            return response
        return FileResponse(
            path.open("rb"),
            as_attachment=True,
            filename=filename,
            content_type=content_type,
        )
