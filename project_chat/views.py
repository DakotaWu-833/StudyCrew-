from drf_spectacular.utils import extend_schema, OpenApiTypes
from rest_framework.decorators import api_view
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from config.serializers import EmptyActionSerializer
from operations.services import consume_rate
from django.conf import settings
from . import serializers, services


def validate(serializer, data):
    value = serializer(data=data)
    value.is_valid(raise_exception=True)
    return value.validated_data


@extend_schema(methods=["GET"], parameters=[serializers.ChatQuery], responses=OpenApiTypes.OBJECT)
@extend_schema(methods=["POST"], request=serializers.ChatSendInput, responses={201: OpenApiTypes.OBJECT, 200: OpenApiTypes.OBJECT})
@api_view(["GET", "POST"])
def messages(request, project_id):
    if request.method == "GET":
        return Response(services.conversation(request.user, project_id, **validate(serializers.ChatQuery, request.query_params)))
    values = validate(serializers.ChatSendInput, request.data)
    if settings.OPERATIONS_RATE_LIMITS and not consume_rate("chat-send", request.user.pk, limit=30, seconds=60):
        raise Throttled()
    message, created = services.send_message(request.user, project_id, **values)
    return Response(services.serialize_message(message, request.user), status=201 if created else 200)


@extend_schema(request=serializers.ChatRemoveInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def remove(request, project_id, message_id):
    message = services.remove_message(request.user, project_id, message_id, **validate(serializers.ChatRemoveInput, request.data))
    return Response(services.serialize_message(message, request.user))


@extend_schema(request=EmptyActionSerializer, responses={204: None})
@api_view(["POST"])
def presence(request, project_id):
    validate(EmptyActionSerializer, request.data)
    if settings.OPERATIONS_RATE_LIMITS and not consume_rate("chat-presence", request.user.pk, limit=12, seconds=60):
        raise Throttled()
    services.heartbeat(request.user, project_id)
    return Response(status=204)
