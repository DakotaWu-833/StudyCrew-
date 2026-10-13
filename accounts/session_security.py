"""Small shared contract for enforcing MFA-authenticated Django sessions."""

from __future__ import annotations

from datetime import datetime

from django.http import HttpRequest
from django.utils import timezone


MFA_VERIFIED_SESSION_KEY = "mfa_verified_at"


def mark_mfa_verified(request: HttpRequest) -> None:
    """Record MFA only after the one-time challenge has been consumed."""

    request.session[MFA_VERIFIED_SESSION_KEY] = timezone.now().isoformat()
    from accounts.readiness_services import track_device_session
    track_device_session(request, force=True)


def is_mfa_verified(request: HttpRequest) -> bool:
    """Return true only for an authenticated session with a valid marker."""

    if not request.user.is_authenticated:
        return False
    raw_value = request.session.get(MFA_VERIFIED_SESSION_KEY)
    if not isinstance(raw_value, str):
        return False
    try:
        verified_at = datetime.fromisoformat(raw_value)
    except ValueError:
        return False
    return timezone.is_aware(verified_at) and verified_at <= timezone.now()
