"""JSON representations kept separate from transactional domain services."""

from __future__ import annotations

from collections.abc import Mapping

from rest_framework import serializers

from accounts.models import Profile, User
from activity.models import ActivityEvent, ExportJob, Notification
from meetings.models import Meeting, MeetingAttendance
from projects.models import Project, ProjectInvitation, ProjectMembership
from tasks.models import ContentReport, Task, TaskComment


INVITATION_STATUS_CHOICES = ProjectInvitation.Status.choices
TASK_STATUS_CHOICES = Task.Status.choices
MEMBERSHIP_ROLE_CHOICES = ProjectMembership.Role.choices
MUTABLE_MEMBERSHIP_ROLE_CHOICES = (
    ProjectMembership.Role.MEMBER,
    ProjectMembership.Role.FACILITATOR,
)


class StrictFieldsMixin:
    """Reject undeclared and read-only input instead of silently discarding it."""

    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        writable_fields = {field.field_name for field in self._writable_fields}
        unexpected = set(data) - writable_fields
        if unexpected:
            raise serializers.ValidationError(
                {field: "This field is not accepted." for field in sorted(unexpected)}
            )
        return super().to_internal_value(data)


class StrictFieldsSerializer(StrictFieldsMixin, serializers.Serializer):
    pass


class EmptyActionSerializer(StrictFieldsSerializer):
    """Explicitly empty action body; unknown client fields are rejected."""


class ReminderDeliverySerializer(serializers.Serializer):
    recipient_count = serializers.IntegerField(min_value=1, read_only=True)
    sent_at = serializers.DateTimeField(read_only=True)


class UserSummarySerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(source="profile.display_name", read_only=True)

    class Meta:
        model = User
        fields = ("id", "display_name")


class HealthSerializer(serializers.Serializer):
    status = serializers.CharField(read_only=True)
    database = serializers.CharField(read_only=True)


class PermissionSummarySerializer(serializers.Serializer):
    site_moderator = serializers.BooleanField(read_only=True)


class ProfileSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = Profile
        fields = (
            "email",
            "display_name",
            "course_code",
            "time_zone",
            "biography",
            "avatar_url",
            "updated_at",
        )
        read_only_fields = ("updated_at",)


class ProfileReplaceSerializer(ProfileSerializer):
    """A PUT contract that requires every writable profile field."""

    class Meta(ProfileSerializer.Meta):
        extra_kwargs = {
            "display_name": {"required": True},
            "course_code": {"required": True},
            "time_zone": {"required": True},
            "biography": {"required": True},
            "avatar_url": {"required": True},
        }


class MeSerializer(serializers.Serializer):
    user = UserSummarySerializer(read_only=True)
    email = serializers.EmailField(read_only=True)
    profile = ProfileSerializer(read_only=True)
    permissions = PermissionSummarySerializer(read_only=True)


class ProjectSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    created_by = UserSummarySerializer(read_only=True)
    current_user_role = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = (
            "id",
            "name",
            "description",
            "due_at",
            "created_by",
            "created_at",
            "updated_at",
            "archived_at",
            "current_user_role",
            "member_count",
        )
        read_only_fields = (
            "id",
            "created_by",
            "created_at",
            "updated_at",
            "archived_at",
            "current_user_role",
            "member_count",
        )

    def get_current_user_role(self, obj: Project) -> str | None:
        request = self.context.get("request")
        if request is None:
            return None
        membership = next(
            (
                item
                for item in getattr(obj, "_active_memberships", [])
                if item.user_id == request.user.id
            ),
            None,
        )
        if membership is None:
            membership = obj.memberships.filter(
                user=request.user,
                removed_at__isnull=True,
            ).first()
        return membership.role if membership else None

    def get_member_count(self, obj: Project) -> int:
        prefetched = getattr(obj, "_active_memberships", None)
        return len(prefetched) if prefetched is not None else obj.memberships.active().count()

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Project name must contain at least 3 characters.")
        return value


class ProjectReplaceSerializer(ProjectSerializer):
    """A PUT contract that replaces every writable project field."""

    class Meta(ProjectSerializer.Meta):
        extra_kwargs = {
            "name": {"required": True},
            "description": {"required": True},
            "due_at": {"required": True},
        }


class ProjectListQuerySerializer(serializers.Serializer):
    scope = serializers.ChoiceField(
        choices=("active", "archived", "all"),
        default="active",
        required=False,
    )


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)

    class Meta:
        model = ProjectMembership
        fields = ("id", "project", "user", "role", "joined_at", "removed_at")
        read_only_fields = ("id", "project", "user", "joined_at", "removed_at")


class MembershipRoleUpdateSerializer(StrictFieldsSerializer):
    role = serializers.ChoiceField(choices=MUTABLE_MEMBERSHIP_ROLE_CHOICES)


class InvitationSerializer(StrictFieldsMixin, serializers.ModelSerializer):
    project_name = serializers.CharField(source="project.name", read_only=True)
    invited_by = UserSummarySerializer(read_only=True)

    class Meta:
        model = ProjectInvitation
        fields = (
            "id",
            "project",
            "project_name",
            "invited_email",
            "invited_by",
            "status",
            "expires_at",
            "responded_at",
            "created_at",
        )
        read_only_fields = (
            "id",
            "project_name",
            "invited_by",
            "status",
            "expires_at",
            "responded_at",
            "created_at",
        )


class InvitationDispatchSerializer(InvitationSerializer):
    """Invitation response returned only once with its share token."""

    share_token = serializers.CharField(read_only=True)

    class Meta(InvitationSerializer.Meta):
        fields = InvitationSerializer.Meta.fields + ("share_token",)
        read_only_fields = InvitationSerializer.Meta.read_only_fields + ("share_token",)


class TaskSerializer(serializers.ModelSerializer):
    created_by = UserSummarySerializer(read_only=True)
    assignees = UserSummarySerializer(many=True, read_only=True)
    comment_count = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = (
            "id",
            "project",
            "title",
            "description",
            "status",
            "priority",
            "blocker_note",
            "due_at",
            "completed_at",
            "created_by",
            "created_at",
            "updated_at",
            "archived_at",
            "assignees",
            "comment_count",
        )
        read_only_fields = fields

    def get_comment_count(self, obj: Task) -> int:
        return obj.comments.filter(deleted_at__isnull=True).count()


class TaskWriteSerializer(StrictFieldsSerializer):
    title = serializers.CharField(min_length=3, max_length=120, trim_whitespace=True, required=False)
    description = serializers.CharField(max_length=4000, allow_blank=True, required=False)
    priority = serializers.ChoiceField(choices=Task.Priority.choices, required=False)
    due_at = serializers.DateTimeField(allow_null=True, required=False)


class TaskCreateSerializer(TaskWriteSerializer):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    title = serializers.CharField(min_length=3, max_length=120, trim_whitespace=True)


class TaskReplaceSerializer(TaskWriteSerializer):
    title = serializers.CharField(min_length=3, max_length=120, trim_whitespace=True)
    description = serializers.CharField(max_length=4000, allow_blank=True)
    priority = serializers.ChoiceField(choices=Task.Priority.choices)
    due_at = serializers.DateTimeField(allow_null=True)


class TaskListQuerySerializer(serializers.Serializer):
    project = serializers.UUIDField()
    scope = serializers.ChoiceField(
        choices=("active", "archived", "all"),
        required=False,
        default="active",
    )
    q = serializers.CharField(required=False, allow_blank=True, max_length=200)
    status = serializers.ChoiceField(
        choices=Task.Status.choices,
        required=False,
        allow_blank=True,
    )
    priority = serializers.ChoiceField(
        choices=Task.Priority.choices,
        required=False,
        allow_blank=True,
    )
    assignee = serializers.UUIDField(required=False)
    due = serializers.ChoiceField(
        choices=("overdue", "upcoming", "none"),
        required=False,
        allow_blank=True,
    )


class AssigneeUpdateSerializer(StrictFieldsSerializer):
    assignee_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=True,
    )


class TaskTransitionSerializer(StrictFieldsSerializer):
    status = serializers.ChoiceField(choices=Task.Status.choices)
    blocker_note = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class CommentSerializer(serializers.ModelSerializer):
    author = UserSummarySerializer(read_only=True)
    body = serializers.SerializerMethodField()
    is_deleted = serializers.BooleanField(read_only=True)

    class Meta:
        model = TaskComment
        fields = (
            "id",
            "task",
            "author",
            "body",
            "created_at",
            "edited_at",
            "deleted_at",
            "is_deleted",
        )
        read_only_fields = fields

    def get_body(self, obj: TaskComment) -> str:
        return "" if obj.deleted_at else obj.body


class CommentWriteSerializer(StrictFieldsSerializer):
    body = serializers.CharField(min_length=1, max_length=2000, trim_whitespace=True)


class CommentCreateSerializer(CommentWriteSerializer):
    task = serializers.PrimaryKeyRelatedField(queryset=Task.objects.all())
    mentioned_user_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        default=list,
    )


class CommentListQuerySerializer(serializers.Serializer):
    task = serializers.UUIDField()


class CommentReportSerializer(StrictFieldsSerializer):
    reason = serializers.ChoiceField(choices=ContentReport.Reason.choices)
    details = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class CommentReportResultSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True, help_text="Current moderation state.")


class MeetingSerializer(serializers.ModelSerializer):
    organiser = UserSummarySerializer(read_only=True)
    attendance_counts = serializers.SerializerMethodField()
    my_response = serializers.SerializerMethodField()
    my_availability_note = serializers.SerializerMethodField()

    class Meta:
        model = Meeting
        fields = (
            "id",
            "project",
            "organiser",
            "title",
            "starts_at",
            "ends_at",
            "location",
            "agenda",
            "cancelled_at",
            "archived_at",
            "lifecycle_state",
            "created_at",
            "updated_at",
            "attendance_counts",
            "my_response",
            "my_availability_note",
        )
        read_only_fields = fields

    def get_attendance_counts(self, obj: Meeting) -> dict[str, int]:
        counts = {value: 0 for value in MeetingAttendance.Response.values}
        for response in obj.attendances.all():
            counts[response.response] += 1
        return counts

    def get_my_response(self, obj: Meeting) -> str:
        request = self.context.get("request")
        if request is None:
            return MeetingAttendance.Response.PENDING
        response = next(
            (item.response for item in obj.attendances.all() if item.user_id == request.user.id),
            MeetingAttendance.Response.PENDING,
        )
        return response

    def get_my_availability_note(self, obj: Meeting) -> str:
        request = self.context.get("request")
        if request is None:
            return ""
        return next(
            (
                item.availability_note
                for item in obj.attendances.all()
                if item.user_id == request.user.id
            ),
            "",
        )


class MeetingWriteSerializer(StrictFieldsSerializer):
    title = serializers.CharField(min_length=3, max_length=120, trim_whitespace=True, required=False)
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    location = serializers.CharField(max_length=2048, allow_blank=True, required=False)
    agenda = serializers.CharField(max_length=4000, allow_blank=True, required=False)


class MeetingCreateSerializer(MeetingWriteSerializer):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    title = serializers.CharField(min_length=3, max_length=120, trim_whitespace=True)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class MeetingReplaceSerializer(MeetingWriteSerializer):
    title = serializers.CharField(min_length=3, max_length=120, trim_whitespace=True)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    location = serializers.CharField(max_length=2048, allow_blank=True)
    agenda = serializers.CharField(max_length=4000, allow_blank=True)


class MeetingListQuerySerializer(serializers.Serializer):
    project = serializers.UUIDField()
    scope = serializers.ChoiceField(
        choices=("active", "archived", "all"),
        required=False,
        default="active",
    )


class RSVPSerializer(StrictFieldsSerializer):
    response = serializers.ChoiceField(choices=MeetingAttendance.Response.choices)
    availability_note = serializers.CharField(max_length=500, allow_blank=True, required=False, default="")


class HolidayAdvisorySerializer(serializers.Serializer):
    meeting_date = serializers.DateField(read_only=True)
    available = serializers.BooleanField(read_only=True)
    is_public_holiday = serializers.BooleanField(allow_null=True, read_only=True)
    holiday_name = serializers.CharField(allow_null=True, read_only=True)
    source = serializers.ChoiceField(
        choices=("live", "cache", "stale", "unavailable"),
        read_only=True,
    )
    message = serializers.CharField(read_only=True)


class ActivityEventSerializer(serializers.ModelSerializer):
    actor = UserSummarySerializer(read_only=True)

    class Meta:
        model = ActivityEvent
        fields = (
            "id",
            "project",
            "actor",
            "event_type",
            "target_type",
            "target_id",
            "metadata",
            "occurred_at",
        )
        read_only_fields = fields


class NotificationSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source="project.name", read_only=True)
    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        model = Notification
        fields = (
            "id",
            "project",
            "project_name",
            "notification_type",
            "target_url",
            "created_at",
            "read_at",
            "is_read",
        )
        read_only_fields = fields


class ExportJobSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = ExportJob
        fields = (
            "id",
            "project",
            "format",
            "range_start",
            "range_end",
            "status",
            "error_message",
            "created_at",
            "completed_at",
            "expires_at",
            "download_url",
        )
        read_only_fields = (
            "id",
            "status",
            "error_message",
            "created_at",
            "completed_at",
            "expires_at",
            "download_url",
        )

    def get_download_url(self, obj: ExportJob) -> str | None:
        if obj.status != ExportJob.Status.READY:
            return None
        request = self.context.get("request")
        path = f"/api/v1/exports/{obj.id}/download/"
        return request.build_absolute_uri(path) if request else path


class ExportRequestSerializer(StrictFieldsSerializer):
    project = serializers.PrimaryKeyRelatedField(queryset=Project.objects.all())
    format = serializers.ChoiceField(choices=ExportJob.Format.choices)
    range_start = serializers.DateField()
    range_end = serializers.DateField()


class InsightsQuerySerializer(serializers.Serializer):
    range_start = serializers.DateField(required=False)
    range_end = serializers.DateField(required=False)
    event_type = serializers.ChoiceField(
        choices=[("", "All"), *ActivityEvent.Type.choices],
        required=False,
        allow_blank=True,
        default="",
    )


class ActivityTimelineQuerySerializer(serializers.Serializer):
    range_start = serializers.DateField(required=False)
    range_end = serializers.DateField(required=False)
    event_type = serializers.ChoiceField(
        choices=[("", "All"), *ActivityEvent.Type.choices],
        required=False,
        allow_blank=True,
        default="",
    )
    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    member = serializers.UUIDField(required=False)
    page = serializers.IntegerField(required=False, min_value=1, default=1)


class MemberInsightSerializer(serializers.Serializer):
    user_id = serializers.UUIDField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    role = serializers.ChoiceField(choices=ProjectMembership.Role.choices, read_only=True)
    total_events = serializers.IntegerField(min_value=0, read_only=True)
    completed_tasks = serializers.IntegerField(min_value=0, read_only=True)
    comments = serializers.IntegerField(min_value=0, read_only=True)
    accepted_meetings = serializers.IntegerField(min_value=0, read_only=True)


class InsightDistributionPointSerializer(serializers.Serializer):
    key = serializers.CharField(read_only=True)
    label = serializers.CharField(read_only=True)
    count = serializers.IntegerField(min_value=0, read_only=True)


class InsightDailyCountSerializer(serializers.Serializer):
    date = serializers.DateField(read_only=True)
    count = serializers.IntegerField(min_value=0, read_only=True)


class InsightDailyCycleSerializer(InsightDailyCountSerializer):
    average_hours = serializers.FloatField(min_value=0, allow_null=True, read_only=True)


class InsightsChartsSerializer(serializers.Serializer):
    task_status = InsightDistributionPointSerializer(many=True, read_only=True)
    task_priority = InsightDistributionPointSerializer(many=True, read_only=True)
    task_assignees = InsightDistributionPointSerializer(many=True, read_only=True)
    tasks_created = InsightDailyCountSerializer(many=True, read_only=True)
    completion_cycle = InsightDailyCycleSerializer(many=True, read_only=True)


class InsightsResponseSerializer(serializers.Serializer):
    range_start = serializers.DateField(read_only=True)
    range_end = serializers.DateField(read_only=True)
    event_type = serializers.CharField(allow_blank=True, read_only=True)
    members = MemberInsightSerializer(many=True, read_only=True)
    events = ActivityEventSerializer(many=True, read_only=True)
    events_truncated = serializers.BooleanField(read_only=True)
    charts = InsightsChartsSerializer(read_only=True)


class ActivityTimelineResponseSerializer(serializers.Serializer):
    events = ActivityEventSerializer(many=True, read_only=True)
    events_total = serializers.IntegerField(min_value=0, read_only=True)
    events_page = serializers.IntegerField(min_value=1, read_only=True)
    events_pages = serializers.IntegerField(min_value=1, read_only=True)
    events_page_size = serializers.IntegerField(min_value=1, read_only=True)


class OwnershipTransferSerializer(StrictFieldsSerializer):
    previous_owner_role = serializers.ChoiceField(
        choices=MUTABLE_MEMBERSHIP_ROLE_CHOICES,
        required=False,
        default=ProjectMembership.Role.FACILITATOR,
    )


class InvitationListQuerySerializer(serializers.Serializer):
    project = serializers.UUIDField(required=False)


class MembershipListQuerySerializer(serializers.Serializer):
    project = serializers.UUIDField()


class NotificationListQuerySerializer(serializers.Serializer):
    unread = serializers.BooleanField(required=False)
