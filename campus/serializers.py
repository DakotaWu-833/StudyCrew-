from rest_framework import serializers
from tasks.models import Task


class TermInput(serializers.Serializer):
    university = serializers.CharField(max_length=120)
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    name = serializers.CharField(max_length=80)


class CourseInput(serializers.Serializer):
    university = serializers.CharField(max_length=120)
    code = serializers.CharField(max_length=30)
    name = serializers.CharField(max_length=120)


class CourseLinkInput(serializers.Serializer):
    course = serializers.UUIDField()
    term = serializers.UUIDField()


class CopyTermInput(serializers.Serializer):
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    name = serializers.CharField(max_length=80)
    projects = serializers.ListField(child=serializers.UUIDField(), max_length=20, default=list)


class MilestoneInput(serializers.Serializer):
    title = serializers.CharField(max_length=120, required=False)
    due_at = serializers.DateTimeField(allow_null=True, required=False)
    done = serializers.BooleanField(required=False)


class TaskPlanInput(serializers.Serializer):
    tags = serializers.ListField(child=serializers.CharField(max_length=30), max_length=10, required=False)
    estimate_hours = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0, max_value=1000, allow_null=True, required=False)
    parent = serializers.UUIDField(allow_null=True, required=False)
    milestone = serializers.UUIDField(allow_null=True, required=False)
    reviewer = serializers.UUIDField(allow_null=True, required=False)
    acceptance = serializers.CharField(max_length=4000, allow_blank=True, required=False)
    internal_due_at = serializers.DateTimeField(allow_null=True, required=False)
    official_due_at = serializers.DateTimeField(allow_null=True, required=False)
    outcome_url = serializers.CharField(max_length=2048, allow_blank=True, required=False)
    dependencies = serializers.ListField(child=serializers.UUIDField(), max_length=100, required=False)


class ChecklistInput(serializers.Serializer):
    text = serializers.CharField(max_length=300, required=False)
    checked = serializers.BooleanField(required=False)


class ReviewInput(serializers.Serializer):
    approved = serializers.BooleanField()
    note = serializers.CharField(max_length=1000, allow_blank=True, default="")


class RevisionInput(serializers.Serializer):
    revision = serializers.IntegerField(min_value=1)


class AgreementInput(serializers.Serializer):
    expected_revision = serializers.IntegerField(min_value=0, required=False)
    body = serializers.CharField(max_length=6000)


class ResourceInput(serializers.Serializer):
    title = serializers.CharField(max_length=150, required=False)
    url = serializers.CharField(max_length=2048, required=False)
    description = serializers.CharField(max_length=1000, allow_blank=True, required=False)
    tags = serializers.ListField(child=serializers.CharField(max_length=30), max_length=10, required=False)
    pinned = serializers.BooleanField(required=False)


class SubmissionInput(serializers.Serializer):
    internal_due_at = serializers.DateTimeField(allow_null=True, required=False)
    official_due_at = serializers.DateTimeField(allow_null=True, required=False)


class ReceiptInput(serializers.Serializer):
    receipt_url = serializers.CharField(max_length=2048, allow_blank=True, default="")
    receipt_reference = serializers.CharField(max_length=200, allow_blank=True, default="")


class LeaveInput(serializers.Serializer):
    handover_user = serializers.UUIDField(allow_null=True, default=None)
    new_owner = serializers.UUIDField(allow_null=True, default=None)


class JoinLinkInput(serializers.Serializer):
    expires_at = serializers.DateTimeField()
    max_uses = serializers.IntegerField(min_value=1, max_value=50, default=10)


class JoinInput(serializers.Serializer):
    token = serializers.CharField(min_length=20, max_length=100, trim_whitespace=True)


class ResolveInput(serializers.Serializer):
    approve = serializers.BooleanField()


class TemplateInput(serializers.Serializer):
    template = serializers.ChoiceField(choices=("report", "software", "presentation", "data_analysis", "design", "research"))


class TaskCreateInput(serializers.Serializer):
    title = serializers.CharField(min_length=3, max_length=120)
    parent = serializers.UUIDField()


class TaskCopyInput(serializers.Serializer):
    title = serializers.CharField(min_length=3, max_length=120)
    reuse_dependencies = serializers.BooleanField(default=False)


class TaskBulkInput(serializers.Serializer):
    tasks = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=50)
    assignees = serializers.ListField(child=serializers.UUIDField(), max_length=100, required=False)
    priority = serializers.ChoiceField(choices=Task.Priority.choices, required=False)
    internal_due_at = serializers.DateTimeField(allow_null=True, required=False)

    def validate(self, data):
        if not any(key in data for key in ("assignees", "priority", "internal_due_at")):
            raise serializers.ValidationError("Choose a field to update.")
        return data
