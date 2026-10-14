from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.exceptions import Throttled
from rest_framework.response import Response

from operations.services import consume_rate
from . import serializers, services
from . import agent
from . import actions
from .policies import require_project


def private_response(data):
    response = Response(data)
    response["Cache-Control"] = "private, no-store"
    response["Vary"] = "Cookie"
    return response


@extend_schema(responses=serializers.CapabilitiesOutput)
@api_view(["GET"])
def capabilities(request, project_id):
    return private_response(services.capabilities(request.user, project_id))


def question(request, project_id, *, generate):
    require_project(request.user, project_id)
    values = serializers.QuestionInput(data=request.data)
    values.is_valid(raise_exception=True)
    if settings.OPERATIONS_RATE_LIMITS and not consume_rate("project-rag", request.user.pk, limit=12, seconds=60):
        raise Throttled()
    if generate and settings.OPERATIONS_RATE_LIMITS and not consume_rate("project-rag-generation", request.user.pk, limit=4, seconds=60):
        raise Throttled()
    handler = services.ask if generate else services.search
    return private_response(handler(request.user, project_id, **values.validated_data))


@extend_schema(request=serializers.QuestionInput, responses=serializers.SearchOutput)
@api_view(["POST"])
def search(request, project_id):
    return question(request, project_id, generate=False)


@extend_schema(request=serializers.QuestionInput, responses=serializers.AnswerOutput)
@api_view(["POST"])
def ask(request, project_id):
    return question(request, project_id, generate=True)


@extend_schema(methods=["GET"], responses=serializers.AssistantCapabilitiesOutput)
@extend_schema(methods=["POST"], request=serializers.AssistantInput, responses=serializers.AssistantOutput)
@api_view(["GET", "POST"])
def assistant(request, project_id):
    if request.method == "GET":
        return private_response(agent.capabilities(request.user, project_id))
    require_project(request.user, project_id)
    values = serializers.AssistantInput(data=request.data)
    values.is_valid(raise_exception=True)
    if settings.OPERATIONS_RATE_LIMITS and not consume_rate("project-assistant", request.user.pk, limit=4, seconds=60):
        raise Throttled()
    return private_response(agent.run(request.user, project_id, **values.validated_data))


@extend_schema(request=serializers.ApproveTaskInput, responses=serializers.TaskReceiptOutput)
@api_view(["POST"])
def approve_task(request, project_id):
    require_project(request.user, project_id)
    values = serializers.ApproveTaskInput(data=request.data)
    values.is_valid(raise_exception=True)
    if settings.OPERATIONS_RATE_LIMITS and not consume_rate("assistant-task-approval", request.user.pk, limit=10, seconds=60):
        raise Throttled()
    return private_response(actions.approve_task(request.user, project_id, **values.validated_data))
