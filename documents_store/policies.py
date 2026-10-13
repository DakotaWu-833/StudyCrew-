from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404

from projects.models import Project
from projects.policies import active_membership, require_project_member, is_project_manager, is_authenticated_active


def project_access(user, project_id, *, write=False, lock=False):
    if not is_authenticated_active(user):
        raise Http404
    query = Project.objects.all() if lock else Project.objects.for_user(user)
    if lock:
        query = query.select_for_update()
    project = query.filter(pk=project_id).first()
    if not project or active_membership(user, project) is None:
        raise Http404
    require_project_member(user, project)
    if write and project.archived_at:
        raise ValidationError("Archived project files are read-only.")
    return project


def can_edit(user, document):
    return document.author_id == user.pk or is_project_manager(user, document.project)


def require_editor(user, document):
    if not can_edit(user, document):
        raise PermissionDenied("Only the author or a project manager can change this file.")
