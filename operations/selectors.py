"""Permission-filtered queries for user inbox and operational summaries."""
from datetime import timedelta
from django.conf import settings
from django.db.models import Count, Q, Sum
from django.utils import timezone
from accounts.policies import require_site_moderator
from activity.models import Notification, ActivityEvent
from projects.models import ProjectMembership
from .models import ContactRequest, OutboundMessage, ServiceMetric, ServiceNotice, SupportTicket, UserAlert, WorkerHeartbeat
from .backup_health import backup_health


def alerts_for(user):
    return UserAlert.objects.filter(user=user, project__memberships__user=user,
                                  project__memberships__removed_at__isnull=True).distinct()


def tickets_for(user):
    return SupportTicket.objects.filter(user=user).prefetch_related("replies__author__profile")


def operations_summary(actor):
    require_site_moderator(actor)
    now = timezone.now()
    deliveries = dict(OutboundMessage.objects.values_list("status").annotate(count=Count("id")))
    active_teams = ActivityEvent.objects.filter(occurred_at__gte=now - timedelta(days=7)).values("project_id").distinct().count()
    return {
        "backup": backup_health(),
        "mail": deliveries,
        "oldest_queued_at": OutboundMessage.objects.filter(status="queued").order_by("created_at").values_list("created_at", flat=True).first(),
        "workers": list(WorkerHeartbeat.objects.values("name", "last_run_at", "detail")),
        "requests": list(ServiceMetric.objects.filter(day__gte=now.date() - timedelta(days=7)).values()),
        "open_support": SupportTicket.objects.exclude(status="resolved").count() + ContactRequest.objects.filter(verified_at__isnull=False, resolved_at__isnull=True).count(),
        "weekly_active_teams": active_teams,
        "active_memberships": ProjectMembership.objects.active().count(),
        "mail_budget": {"daily_limit": settings.MAIL_DAILY_LIMIT},
    }


def current_notices():
    now = timezone.now()
    return ServiceNotice.objects.filter(starts_at__lte=now).filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now)).order_by("-starts_at")[:10]
