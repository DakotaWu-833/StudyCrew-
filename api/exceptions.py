"""Return a stable JSON error contract without exposing internal details."""

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from projects.exceptions import ProjectDomainError
from projects.workflows import InvitationDeliveryError


logger = logging.getLogger(__name__)


def _django_validation_detail(exc: DjangoValidationError):
    if hasattr(exc, "message_dict"):
        return exc.message_dict
    return {"non_field_errors": list(exc.messages)}


def safe_exception_handler(exc, context):
    if isinstance(exc, InvitationDeliveryError):
        logger.warning("Invitation delivery failed; the transaction was rolled back.")
        return Response(
            {
                "error": {
                    "code": "service_unavailable",
                    "message": "The invitation email could not be sent. Please try again.",
                }
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(_django_validation_detail(exc))
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied(str(exc) or "Permission denied.")
    elif isinstance(exc, ProjectDomainError):
        exc = exceptions.ValidationError({"non_field_errors": [str(exc)]})
    elif isinstance(exc, IntegrityError):
        logger.warning("Database constraint rejected an API request.")
        exc = exceptions.ValidationError(
            {"non_field_errors": ["The request conflicts with existing data."]}
        )

    response = exception_handler(exc, context)
    if response is None:
        logger.error("Unhandled API error", exc_info=(type(exc), exc, exc.__traceback__))
        return Response(
            {
                "error": {
                    "code": "server_error",
                    "message": "The request could not be completed.",
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if response.status_code >= 500:
        response.data = {
            "error": {
                "code": "server_error",
                "message": "The request could not be completed.",
            }
        }
        return response

    original = response.data
    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        code = "not_authenticated"
        message = "Authentication and MFA are required."
        fields = None
    elif response.status_code == status.HTTP_403_FORBIDDEN:
        code = "permission_denied"
        message = "You do not have permission to perform this action."
        fields = None
    elif response.status_code == status.HTTP_404_NOT_FOUND:
        code = "not_found"
        message = "The requested resource was not found."
        fields = None
    elif response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
        code = "method_not_allowed"
        message = "This HTTP method is not supported for the resource."
        fields = None
    elif response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        code = "throttled"
        message = "Too many requests. Please try again later."
        fields = None
    else:
        code = "validation_error"
        message = "Please correct the highlighted fields."
        fields = original

    payload = {"error": {"code": code, "message": message}}
    if fields is not None:
        payload["error"]["fields"] = fields
    response.data = payload
    return response
