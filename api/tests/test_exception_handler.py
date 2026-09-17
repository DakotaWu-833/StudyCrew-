from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.test import SimpleTestCase
from rest_framework import exceptions, status

from api.exceptions import safe_exception_handler
from projects.exceptions import ProjectDomainError
from projects.workflows import InvitationDeliveryError


class SafeExceptionHandlerTests(SimpleTestCase):
    def assert_error(self, response, *, status_code, code, fields=False):
        self.assertEqual(response.status_code, status_code)
        self.assertEqual(response.data["error"]["code"], code)
        self.assertEqual("fields" in response.data["error"], fields)

    def test_django_validation_errors_preserve_field_and_non_field_details(self):
        field_response = safe_exception_handler(
            DjangoValidationError({"name": ["Choose another name."]}), {}
        )
        self.assert_error(
            field_response,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="validation_error",
            fields=True,
        )
        self.assertIn("name", field_response.data["error"]["fields"])

        non_field_response = safe_exception_handler(
            DjangoValidationError("The values conflict."), {}
        )
        self.assertIn(
            "non_field_errors", non_field_response.data["error"]["fields"]
        )

    def test_expected_django_and_domain_errors_use_safe_contract(self):
        permission_response = safe_exception_handler(
            DjangoPermissionDenied("Private detail that is not returned"), {}
        )
        self.assert_error(
            permission_response,
            status_code=status.HTTP_403_FORBIDDEN,
            code="permission_denied",
        )

        blank_permission_response = safe_exception_handler(
            DjangoPermissionDenied(), {}
        )
        self.assert_error(
            blank_permission_response,
            status_code=status.HTTP_403_FORBIDDEN,
            code="permission_denied",
        )

        domain_response = safe_exception_handler(
            ProjectDomainError("Expected workflow conflict."), {}
        )
        self.assert_error(
            domain_response,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="validation_error",
            fields=True,
        )

    def test_integrity_error_is_logged_and_redacted(self):
        with self.assertLogs("api.exceptions", level="WARNING"):
            response = safe_exception_handler(
                IntegrityError("unique_project_membership exposed detail"), {}
            )
        self.assert_error(
            response,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="validation_error",
            fields=True,
        )
        self.assertNotIn("unique_project_membership", str(response.data))

    def test_invitation_delivery_failure_is_retryable_and_safe(self):
        with self.assertLogs("api.exceptions", level="WARNING"):
            response = safe_exception_handler(
                InvitationDeliveryError("SMTP host and password detail"), {}
            )
        self.assert_error(
            response,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="service_unavailable",
        )
        self.assertNotIn("SMTP host", str(response.data))

    def test_standard_http_failures_have_stable_codes_without_fields(self):
        cases = (
            (
                exceptions.NotAuthenticated(),
                status.HTTP_401_UNAUTHORIZED,
                "not_authenticated",
            ),
            (
                exceptions.PermissionDenied(),
                status.HTTP_403_FORBIDDEN,
                "permission_denied",
            ),
            (exceptions.NotFound(), status.HTTP_404_NOT_FOUND, "not_found"),
            (
                exceptions.MethodNotAllowed("TRACE"),
                status.HTTP_405_METHOD_NOT_ALLOWED,
                "method_not_allowed",
            ),
            (
                exceptions.Throttled(wait=3),
                status.HTTP_429_TOO_MANY_REQUESTS,
                "throttled",
            ),
        )
        for exc, status_code, code in cases:
            with self.subTest(code=code):
                response = safe_exception_handler(exc, {})
                self.assert_error(response, status_code=status_code, code=code)

    def test_drf_validation_error_retains_structured_fields(self):
        response = safe_exception_handler(
            exceptions.ValidationError({"title": ["This field is required."]}), {}
        )
        self.assert_error(
            response,
            status_code=status.HTTP_400_BAD_REQUEST,
            code="validation_error",
            fields=True,
        )
        self.assertIn("title", response.data["error"]["fields"])

    def test_known_and_unknown_server_errors_are_redacted(self):
        known_response = safe_exception_handler(exceptions.APIException("secret"), {})
        self.assert_error(
            known_response,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="server_error",
        )
        self.assertNotIn("secret", str(known_response.data))

        with self.assertLogs("api.exceptions", level="ERROR"):
            unknown_response = safe_exception_handler(
                RuntimeError("internal implementation detail"), {}
            )
        self.assert_error(
            unknown_response,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="server_error",
        )
        self.assertNotIn("internal implementation detail", str(unknown_response.data))
