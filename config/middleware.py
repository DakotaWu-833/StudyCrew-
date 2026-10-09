"""Small security middleware kept independent of application views."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse


class SecurityHeadersMiddleware:
    """Apply a conservative browser security policy to every response."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'none'; object-src 'none'; img-src 'self' data: blob:; "
            "font-src 'self'; style-src 'self'; script-src 'self'; "
            "connect-src 'self'",
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        if request.path.startswith(("/api/", "/app/", "/account/", "/control/", "/help/")):
            response.headers.setdefault("Cache-Control", "no-store, private")
        if request.path.startswith(("/account/", "/help/verify/", "/api/v1/coordination/subscriptions/feed/")):
            # Origin-only referrers exclude bearer paths/query strings while
            # preserving a same-origin Origin header on real browser form posts.
            response.headers["Referrer-Policy"] = "strict-origin"
        return response
