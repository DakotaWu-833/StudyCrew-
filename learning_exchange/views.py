from django.http import HttpResponse
from django.core.exceptions import ValidationError
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiTypes, OpenApiParameter
from . import services
from .parser import MAX_BYTES
from .serializers import PreviewInput, ConfirmInput


def attachment(content, filename):
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@extend_schema(parameters=[OpenApiParameter("page", int)], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def overview(request, project_id):
    return Response(services.overview(actor=request.user, project_id=project_id, page=request.GET.get("page", 1)))


@extend_schema(request=PreviewInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def preview(request, project_id):
    parsed = request.data
    if getattr(request._request, "private_upload_rejected", False):
        raise ValidationError({"file": "Upload exceeds the size limit or contains multiple files."})
    payload = PreviewInput(data=parsed)
    payload.is_valid(raise_exception=True)
    data = payload.validated_data
    content = data.pop("file").read(MAX_BYTES + 1)
    return Response(services.preview(actor=request.user, project_id=project_id, content=content, **data))


@extend_schema(request=ConfirmInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def confirm(request, project_id):
    payload = ConfirmInput(data=request.data)
    payload.is_valid(raise_exception=True)
    return Response(services.confirm(actor=request.user, project_id=project_id, **payload.validated_data))


@extend_schema(responses={(200, "text/csv"): OpenApiTypes.STR})
@api_view(["GET"])
def export(request, project_id, batch_id=None):
    return attachment(services.csv_export(actor=request.user, project_id=project_id, batch_id=batch_id), "studycrew-assignments.csv")


@extend_schema(responses={(200, "text/csv"): OpenApiTypes.STR})
@api_view(["GET"])
def sample(request):
    return attachment("source_id,title,description,official_due_at,priority\r\nexample-assignment-1,Example assignment,Replace this sample with your assignment brief,2026-11-15T17:00:00+11:00,medium\r\n", "studycrew-assignment-sample.csv")
