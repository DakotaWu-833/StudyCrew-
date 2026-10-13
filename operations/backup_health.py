"""Content-free freshness of a successfully verified automatic snapshot."""
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from .models import WorkerHeartbeat


def backup_health():
    row = WorkerHeartbeat.objects.filter(name="backup").first()
    healthy = bool(row and row.detail.get("verified") and row.last_run_at >= timezone.now() - timedelta(hours=settings.BACKUP_MAX_AGE_HOURS))
    return {"healthy": healthy, "last_verified_at": row.last_run_at if row else None,
            "max_age_hours": settings.BACKUP_MAX_AGE_HOURS}
