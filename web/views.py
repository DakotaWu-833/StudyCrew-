from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from activity.models import SiteAuditEvent
from projects.models import Project
from tasks.models import ContentReport
from tasks.services import resolve_report
from web.services import require_site_moderator, set_user_active


def home(request: HttpRequest) -> HttpResponse:
    return render(request, "web/home.html")


def _workspace_asset_version(filename: str) -> str:
    """Change the static URL whenever a rebuilt client asset changes."""

    try:
        return str((settings.BASE_DIR / "static" / "workspace" / filename).stat().st_mtime_ns)
    except OSError:
        return "0"


@login_required
@ensure_csrf_cookie
def dashboard(request: HttpRequest, route: str = "") -> HttpResponse:
    # React owns the nested workspace route; Django only serves the safe shell.
    return render(request, "web/app.html", {
        "workspace_css_version": _workspace_asset_version("workspace.css"),
        "workspace_js_version": _workspace_asset_version("main.js"),
    })


@login_required
def control_dashboard(request: HttpRequest) -> HttpResponse:
    require_site_moderator(request.user)
    query = request.GET.get("q", "").strip()[:100]
    users = get_user_model().objects.select_related("profile").order_by("profile__display_name")
    if query:
        users = users.filter(
            Q(email__icontains=query) | Q(profile__display_name__icontains=query)
        )
    pending_reports = ContentReport.objects.filter(
        status=ContentReport.Status.PENDING
    ).select_related(
        "comment__task__project", "comment__author__profile", "reporter__profile"
    )[:50]
    context = {
        "query": query,
        "users": users[:100],
        "reports": pending_reports,
        "metrics": {
            "users": get_user_model().objects.count(),
            "active_projects": Project.objects.active().count(),
            "pending_reports": ContentReport.objects.filter(
                status=ContentReport.Status.PENDING
            ).count(),
            "control_actions": SiteAuditEvent.objects.count(),
        },
        "recent_actions": SiteAuditEvent.objects.select_related("actor", "actor__profile")[:20],
    }
    return render(request, "web/control.html", context)


def _action_response(request: HttpRequest, *, message: str, payload: dict | None = None):
    if request.headers.get("Accept") == "application/json":
        return JsonResponse({"message": message, **(payload or {})})
    return redirect("web:control_dashboard")


def _validation_response(request: HttpRequest, error: ValidationError):
    message = " ".join(error.messages)
    if request.headers.get("Accept") == "application/json":
        return JsonResponse(
            {"error": {"code": "validation_error", "message": message}},
            status=400,
        )
    messages.error(request, message)
    return redirect("web:control_dashboard")


def _audit_payload(event: SiteAuditEvent | None) -> dict | None:
    if event is None:
        return None
    profile = getattr(event.actor, "profile", None)
    return {
        "id": str(event.id),
        "action": event.get_action_display(),
        "actor": getattr(profile, "display_name", "") or event.actor.email,
        "occurred_at": event.occurred_at.isoformat(),
    }


@require_POST
@login_required
def control_user_status(request: HttpRequest, user_id) -> HttpResponse:
    require_site_moderator(request.user)
    target = get_object_or_404(get_user_model(), pk=user_id)
    previous_state = target.is_active
    raw_active = request.POST.get("active")
    try:
        if raw_active not in {"true", "false"}:
            raise ValidationError({"active": "Choose true or false."})
        target = set_user_active(actor=request.user, target=target, active=raw_active == "true")
    except ValidationError as error:
        return _validation_response(request, error)
    state = "restored" if target.is_active else "suspended"
    audit_event = None
    if previous_state != target.is_active:
        audit_event = SiteAuditEvent.objects.select_related("actor__profile").filter(
            actor=request.user,
            target_type="user",
            target_id=target.id,
            action=SiteAuditEvent.Action.USER_ENABLED if target.is_active else SiteAuditEvent.Action.USER_DISABLED,
        ).first()
    return _action_response(
        request,
        message=f"{target.profile.display_name} was {state}.",
        payload={
            "user_id": str(target.id),
            "is_active": target.is_active,
            "control_actions": SiteAuditEvent.objects.count(),
            "audit_event": _audit_payload(audit_event),
        },
    )


@require_POST
@login_required
def control_report_resolution(request: HttpRequest, report_id) -> HttpResponse:
    require_site_moderator(request.user)
    report = get_object_or_404(ContentReport.objects.select_related("comment"), pk=report_id)
    outcome = request.POST.get("outcome", "")
    remove_comment = request.POST.get("remove_comment") == "true"
    try:
        report = resolve_report(
            report=report,
            actor=request.user,
            outcome=outcome,
            resolution_note=request.POST.get("resolution_note", ""),
            remove_comment=remove_comment,
        )
    except ValidationError as error:
        return _validation_response(request, error)
    audit_event = SiteAuditEvent.objects.select_related("actor__profile").filter(
        actor=request.user,
        target_type="content_report",
        target_id=report.id,
    ).first()
    return _action_response(
        request,
        message="The report was reviewed.",
        payload={
            "report_id": str(report.id),
            "status": report.status,
            "pending_reports": ContentReport.objects.filter(
                status=ContentReport.Status.PENDING
            ).count(),
            "control_actions": SiteAuditEvent.objects.count(),
            "audit_event": _audit_payload(audit_event),
        },
    )
