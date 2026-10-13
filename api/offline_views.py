from django.conf import settings
from django.db import transaction
from django.core.exceptions import PermissionDenied
from accounts.models import User
from projects.models import Project
from projects.policies import require_project_member
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from config.serializers import StrictFieldsSerializer
from operations.services import consume_rate
from tasks.models import Task
from tasks.selectors import task_for_member
from offline_sync.services import EditConflict, synchronize
from api.serializers import TaskSerializer


class OfflineTaskChanges(StrictFieldsSerializer):
    title = serializers.CharField(min_length=3, max_length=120, required=False)
    description = serializers.CharField(max_length=4000, allow_blank=True, required=False)
    priority = serializers.ChoiceField(choices=Task.Priority.choices, required=False)
    due_at = serializers.DateTimeField(allow_null=True, required=False)
    status = serializers.ChoiceField(choices=Task.Status.choices, required=False)
    blocker_note = serializers.CharField(max_length=500, allow_blank=True, required=False)

    def validate(self, values):
        if not values or ("blocker_note" in values and "status" not in values):
            raise serializers.ValidationError("Supply task details or a status change.")
        return values


class OfflineTaskSyncInput(StrictFieldsSerializer):
    expected_user_id = serializers.UUIDField()
    mutation_id = serializers.UUIDField()
    expected_updated_at = serializers.DateTimeField()
    changes = OfflineTaskChanges()


class OfflineTaskSyncResult(serializers.Serializer):
    task = TaskSerializer()
    duplicate = serializers.BooleanField()


class OfflineSyncError(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()


class OfflineSyncConflict(serializers.Serializer):
    error = OfflineSyncError()
    current = TaskSerializer()


@extend_schema(request=OfflineTaskSyncInput, responses={200: OfflineTaskSyncResult, 409: OfflineSyncConflict})
@api_view(["POST"])
def sync_task(request, task_id):
    serializer = OfflineTaskSyncInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    values = dict(serializer.validated_data)
    if values.pop("expected_user_id") != request.user.pk:
        raise PermissionDenied("This offline edit belongs to a different signed-in account.")
    if settings.OPERATIONS_RATE_LIMITS and not consume_rate("offline-sync", request.user.pk, limit=100, seconds=60):
        raise Throttled()
    try:
        task, duplicate = synchronize(actor=request.user, task_id=task_id, **values)
    except EditConflict:
        with transaction.atomic():
            user = User.objects.select_for_update().filter(pk=request.user.pk, is_active=True, closed_at__isnull=True).first()
            if user is None:
                raise PermissionDenied("An active account is required.")
            project_id = Task.objects.filter(pk=task_id).values_list("project_id", flat=True).first()
            project = Project.objects.select_for_update().get(pk=project_id)
            require_project_member(user, project)
            current = task_for_member(task_id=task_id, user=user, include_archived=True)
            return Response({"error": {"code": "edit_conflict", "message": "This task changed on the server. Compare the changes before syncing."},
                             "current": TaskSerializer(current, context={"request": request}).data}, status=409)
    return Response({"task": TaskSerializer(task, context={"request": request}).data, "duplicate": duplicate})
