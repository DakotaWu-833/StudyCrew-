from django.http import Http404

from accounts.models import User
from projects.models import Project


def require_project(user, project_id):
    """Refresh identity: a previously loaded user cannot retain revoked access."""
    if not getattr(user, "is_authenticated", False):
        raise Http404
    current = User.objects.filter(pk=user.pk, is_active=True, closed_at__isnull=True).first()
    project = Project.objects.for_user(current).filter(pk=project_id).first() if current else None
    if project is None:
        raise Http404
    return current, project
