from django.core.exceptions import PermissionDenied, ValidationError

from projects.policies import require_project_member, require_project_manager


def require_writable(user, project):
    membership = require_project_member(user, project)
    if project.archived_at:
        raise ValidationError("Archived projects are read-only.")
    return membership


def require_poll_manager(user, poll):
    membership = require_writable(user, poll.project)
    if poll.creator_id != user.pk and membership.role not in {"owner", "facilitator"}:
        raise PermissionDenied("Only the poll creator, owner or facilitator can close a poll.")
    return membership


def require_claim_reviewer(user, claim):
    require_writable(user, claim.project)
    require_project_manager(user, claim.project)
    if claim.author_id == user.pk or claim.contributors.filter(user=user).exists():
        raise PermissionDenied("A reviewer must be independent of the claimed work.")
