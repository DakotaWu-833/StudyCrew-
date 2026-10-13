import json

from django.http import FileResponse, Http404
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiTypes, OpenApiParameter
from rest_framework.decorators import api_view, parser_classes, permission_classes, authentication_classes
from rest_framework.authentication import SessionAuthentication
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response

from accounts.session_security import is_mfa_verified
from . import services, selectors, serializers


def validate(request, serializer):
    original = request.data
    if getattr(request._request, "private_upload_rejected", False):
        from rest_framework.exceptions import ValidationError
        raise ValidationError({"file": "Upload exceeds the size limit or contains multiple files."})
    data = original.copy()
    if "tags" in data and isinstance(data["tags"], str):
        try:
            tags = json.loads(data["tags"])
        except (ValueError, TypeError):
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"tags": "Provide a JSON array of tags."})
        if hasattr(data, "setlist"):
            data.setlist("tags", tags if isinstance(tags, list) else [tags])
        else:
            data["tags"] = tags
    result = serializer(data=data)
    result.is_valid(raise_exception=True)
    return result.validated_data


@extend_schema(methods=["GET"], parameters=[OpenApiParameter("q", str), OpenApiParameter("folder", str), OpenApiParameter("tag", str), OpenApiParameter("page", int)], responses=OpenApiTypes.OBJECT)
@extend_schema(methods=["POST"], request=serializers.UploadInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["GET", "POST"])
@parser_classes([MultiPartParser, FormParser])
def project_files(request, project_id):
    if request.method == "GET":
        return Response(selectors.documents(request.user, project_id, request.GET.get("q", ""), request.GET.get("folder", ""), request.GET.get("tag", ""), request.GET.get("page", 1)))
    data = validate(request, serializers.UploadInput)
    document = services.upload(actor=request.user, project_id=project_id, upload=data.pop("file"), values=data)
    return Response(selectors.detail(request.user, project_id, document.pk), status=201)


@extend_schema(methods=["GET"], responses=OpenApiTypes.OBJECT)
@extend_schema(methods=["PATCH"], request=serializers.MetadataInput, responses=OpenApiTypes.OBJECT)
@extend_schema(methods=["DELETE"], request=serializers.RevisionInput, responses={204: None})
@api_view(["GET", "PATCH", "DELETE"])
def document_detail(request, project_id, document_id):
    if request.method == "GET":
        return Response(selectors.detail(request.user, project_id, document_id))
    if request.method == "DELETE":
        data = validate(request, serializers.RevisionInput)
        services.remove(actor=request.user, project_id=project_id, document_id=document_id, **data)
        return Response(status=204)
    document = services.update(actor=request.user, project_id=project_id, document_id=document_id, values=validate(request, serializers.MetadataInput))
    return Response(selectors.detail(request.user, project_id, document.pk))


@extend_schema(request=serializers.UploadInput, responses={201: OpenApiTypes.OBJECT})
@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def versions(request, project_id, document_id):
    data = validate(request, serializers.UploadInput)
    document = services.upload(actor=request.user, project_id=project_id, document_id=document_id, upload=data.pop("file"), values=data)
    return Response(selectors.detail(request.user, project_id, document.pk), status=201)


@extend_schema(parameters=[OpenApiParameter("version", OpenApiTypes.UUID)], responses={200: OpenApiTypes.BINARY})
@api_view(["GET"])
@permission_classes([])
@authentication_classes([SessionAuthentication])
def download(request, project_id, document_id):
    # Hide resource existence from unauthenticated and former users, while retaining
    # global session/MFA authentication for actual members and CSRF for writes.
    if not request.user.is_authenticated or not request.user.is_active or not is_mfa_verified(request._request):
        raise Http404
    version_id = request.GET.get("version")
    if version_id:
        from uuid import UUID
        try:
            version_id = UUID(version_id)
        except ValueError:
            raise Http404
    stream, version = services.open_download(user=request.user, project_id=project_id, document_id=document_id, version_id=version_id)
    response = FileResponse(stream, as_attachment=True, filename=version.filename, content_type="application/octet-stream")
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response["Referrer-Policy"] = "no-referrer"
    return response


@extend_schema(parameters=[OpenApiParameter("version", OpenApiTypes.UUID)], responses={200: OpenApiTypes.BINARY})
@api_view(["GET"])
@permission_classes([])
@authentication_classes([SessionAuthentication])
def preview(request, project_id, document_id):
    if not request.user.is_authenticated or not request.user.is_active or not is_mfa_verified(request._request):
        raise Http404
    version_id = request.GET.get("version")
    if version_id:
        from uuid import UUID
        try:
            version_id = UUID(version_id)
        except ValueError:
            raise Http404
    stream, version, truncated = services.open_preview(user=request.user, project_id=project_id,
        document_id=document_id, version_id=version_id)
    content_type = "text/plain; charset=utf-8" if services.preview_kind(version) == "text" else version.content_type
    response = FileResponse(stream, as_attachment=False, filename=version.filename, content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Preview-Truncated"] = "true" if truncated else "false"
    return response


@extend_schema(parameters=[OpenApiParameter("from_version", OpenApiTypes.UUID, required=True),
    OpenApiParameter("to_version", OpenApiTypes.UUID, required=True)], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def compare(request, project_id, document_id):
    data = serializers.DiffInput(data=request.GET)
    data.is_valid(raise_exception=True)
    return Response(services.text_diff(user=request.user, project_id=project_id, document_id=document_id,
        **data.validated_data))


@extend_schema(parameters=[OpenApiParameter("q", str), OpenApiParameter("page", int)], responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
def trash(request, project_id):
    return Response(selectors.trash(request.user, project_id, request.GET.get("q", ""), request.GET.get("page", 1)))


@extend_schema(request=serializers.RevisionInput, responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
def restore(request, project_id, document_id):
    data = validate(request, serializers.RevisionInput)
    document = services.restore(actor=request.user, project_id=project_id, document_id=document_id, **data)
    return Response(selectors.detail(request.user, project_id, document.pk))
