"""Safe error responses that never expose internal exception details."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def _error(request: HttpRequest, status: int, title: str, message: str) -> HttpResponse:
    return render(
        request,
        "errors/error.html",
        {"status": status, "title": title, "error_message": message},
        status=status,
    )


def bad_request(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    return _error(request, 400, "Invalid request", "Please check the submitted information and try again.")


def permission_denied(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    return _error(request, 403, "Access denied", "You do not have permission to access this resource.")


def not_found(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    return _error(request, 404, "Page not found", "The requested page could not be found.")


def server_error(request: HttpRequest) -> HttpResponse:
    return _error(request, 500, "Something went wrong", "The request could not be completed. Please try again.")
