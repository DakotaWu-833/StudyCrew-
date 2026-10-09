"""Bound public write operations and record aggregate, content-free metrics."""
import logging
from time import monotonic

from django.conf import settings
from django.db import DatabaseError
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone
from accounts.services import client_ip
from .models import ServiceMetric
from .services import consume_rate

logger = logging.getLogger(__name__)


class OperationsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = monotonic()
        path = request.path
        actor = getattr(request, "user", None)
        unsafe = request.method not in {"GET", "HEAD", "OPTIONS"}
        if unsafe and settings.MAINTENANCE_MODE and path.startswith("/api/v1/") and not path.startswith("/api/v1/account/") and not path.startswith("/api/v1/operations/support/") and not getattr(actor, "is_staff", False):
            return JsonResponse({"error": {"code": "maintenance", "message": "Changes are temporarily paused for maintenance. Please try again shortly."}}, status=503)
        if unsafe and settings.OPERATIONS_RATE_LIMITS:
            rules = []
            identity = str(actor.pk) if getattr(actor, "is_authenticated", False) else client_ip(request)
            if path.startswith("/account/register/"):
                rules.append(("registration", client_ip(request), 10, 3600))
            if path.startswith("/api/v1/"):
                rules.append(("api-writes", identity, 200, 60))
            if "invitations" in path and request.method == "POST":
                rules.append(("invitation-write", identity, 30, 3600))
            if "send-reminder" in path:
                rules.append(("manual-reminder", identity, 20, 3600))
            if path == "/api/v1/exports/":
                rules.append(("export-request", identity, 10, 3600))
            try:
                for scope, key, limit, seconds in rules:
                    if not consume_rate(scope, key, limit=limit, seconds=seconds):
                        response = JsonResponse({"error": {"code": "throttled", "message": "Too many requests. Please try again later."}}, status=429)
                        response["Retry-After"] = str(seconds)
                        return response
            except DatabaseError:
                logger.warning("Request limiter is unavailable.")
                return JsonResponse({"error": {"code": "unavailable", "message": "Changes are temporarily unavailable. Please try again later."}}, status=503)
        response = self.get_response(request)
        if path.startswith(("/api/v1/", "/account/")):
            group = "account" if path.startswith("/account/") else (path.split("/")[3] if len(path.split("/")) > 3 else "api")
            group = group if group in {"account", "campus", "coordination", "operations", "projects", "tasks", "meetings", "exports", "invitations"} else "api"
            elapsed_ms = int((monotonic() - start) * 1000)
            logger.info("service_request group=%s method=%s status=%s duration_ms=%s", group, request.method, response.status_code, elapsed_ms)
            if not unsafe and response.status_code < 500:
                return response
            try:
                row, _ = ServiceMetric.objects.get_or_create(day=timezone.now().date(), route_group=group)
                ServiceMetric.objects.filter(pk=row.pk).update(requests=F("requests") + 1,
                    errors=F("errors") + int(response.status_code >= 500), total_ms=F("total_ms") + elapsed_ms)
            except DatabaseError:
                logger.warning("Aggregate service metrics are unavailable.")
        return response
