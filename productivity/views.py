from rest_framework.decorators import api_view
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiTypes, OpenApiParameter
from . import services
from .serializers import RecurrenceInput, TimerStopInput, ManualTimeInput, CorrectTimeInput, DiscardTimeInput


def validated(serializer, request):
    payload = serializer(data=request.data)
    payload.is_valid(raise_exception=True)
    return payload.validated_data


@extend_schema(operation_id="productivity_task_overview", parameters=[OpenApiParameter("page", int)], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def task_overview(request, project_id, task_id):
    return Response(services.task_overview(actor=request.user, project_id=project_id, task_id=task_id, page=request.GET.get("page", 1)))


@extend_schema(operation_id="productivity_create_schedule", request=RecurrenceInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def create_schedule(request, project_id, task_id):
    return Response(services.create_schedule(actor=request.user, project_id=project_id, task_id=task_id, **validated(RecurrenceInput, request)), status=201)


@extend_schema(operation_id="productivity_stop_schedule", request=None, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def stop_schedule(request, project_id, task_id, schedule_id):
    return Response(services.stop_schedule(actor=request.user, project_id=project_id, task_id=task_id, schedule_id=schedule_id))


@extend_schema(operation_id="productivity_start_timer", request=None, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def start_timer(request, project_id, task_id):
    return Response(services.start_timer(actor=request.user, project_id=project_id, task_id=task_id), status=201)


@extend_schema(operation_id="productivity_stop_timer", request=TimerStopInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def stop_timer(request, project_id, task_id):
    return Response(services.stop_timer(actor=request.user, project_id=project_id, task_id=task_id, **validated(TimerStopInput, request)))


@extend_schema(operation_id="productivity_active_timer", responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def active_timer(request):
    return Response({"active_timer": services.active_timer(actor=request.user)})


@extend_schema(operation_id="productivity_discard_timer", request=None, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def discard_timer(request):
    return Response(services.discard_timer(actor=request.user))


@extend_schema(operation_id="productivity_add_manual", request=ManualTimeInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def add_manual(request, project_id, task_id):
    return Response(services.add_manual(actor=request.user, project_id=project_id, task_id=task_id, **validated(ManualTimeInput, request)), status=201)


@extend_schema(operation_id="productivity_correct_entry", request=CorrectTimeInput, responses=OpenApiTypes.OBJECT)
@api_view(["PATCH"])
def correct_entry(request, project_id, task_id, entry_id):
    return Response(services.correct_entry(actor=request.user, project_id=project_id, task_id=task_id, entry_id=entry_id, **validated(CorrectTimeInput, request)))


@extend_schema(operation_id="productivity_discard_entry", request=DiscardTimeInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def delete_entry(request, project_id, task_id, entry_id):
    return Response(services.delete_entry(actor=request.user, project_id=project_id, task_id=task_id, entry_id=entry_id, **validated(DiscardTimeInput, request)))


@extend_schema(operation_id="productivity_workload", responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def workload(request, project_id):
    return Response(services.workload(actor=request.user, project_id=project_id))
