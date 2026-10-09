"""Authorised account security read models, with no session secrets exposed."""

from django.contrib.sessions.models import Session
from django.utils import timezone

from accounts.models import AccountDeviceSession, RecoveryEmail
from accounts.readiness_services import PRIVACY_NOTICE, track_device_session


def account_security_summary(request) -> dict:
    from projects.models import ProjectMembership

    track_device_session(request, force=True)
    now = timezone.now()
    live_keys = Session.objects.filter(expire_date__gt=now).values_list("session_key", flat=True)
    devices = AccountDeviceSession.objects.filter(user=request.user, expires_at__gt=now, session_key__in=live_keys)
    recovery = RecoveryEmail.objects.filter(user=request.user).first()
    return {
        "recovery_email": {"email": recovery.email, "verified_at": recovery.verified_at} if recovery else None,
        "devices": [
            {"id": row.pk, "browser": row.browser or "Unknown browser", "first_seen_at": row.first_seen_at,
             "last_seen_at": row.last_seen_at, "expires_at": row.expires_at,
             "current": row.session_key == request.session.session_key}
            for row in devices
        ],
        "owned_projects": list(ProjectMembership.objects.filter(
            user=request.user, removed_at__isnull=True, role="owner", project__archived_at__isnull=True,
        ).values("project_id", "project__name")),
        "privacy": PRIVACY_NOTICE,
        "verification_minutes": 5,
    }
