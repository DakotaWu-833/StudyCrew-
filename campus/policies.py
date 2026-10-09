"""Academic labels do not grant access to shared project content."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404

from projects.models import Project
from projects.policies import require_project_member, require_project_manager


def project_access(*, user, project_id, write=False, manager=False):
    project = get_object_or_404(Project.objects.for_user(user), pk=project_id)
    if manager:
        require_project_manager(user, project)
    else:
        require_project_member(user, project)
    if write and project.archived_at:
        raise ValidationError("Archived projects are read-only.")
    return project


def own_record(*, user, model, pk, writable=False):
    record = get_object_or_404(model, pk=pk, owner=user)
    if writable and getattr(record, "archived_at", None):
        raise ValidationError("Archived terms are read-only.")
    return record


def resource_change(*, user, resource):
    membership = require_project_member(user, resource.project)
    if resource.added_by_id != user.id and membership.role not in ("owner", "facilitator"):
        raise PermissionDenied("Only the author or a project manager can change this link.")
