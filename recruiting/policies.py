from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from operations.models import UserBlock
from projects.policies import is_project_manager


def require_user(user):
    if not (getattr(user, "is_authenticated", False) and user.is_active and user.closed_at is None and user.email_verified_at):
        raise PermissionDenied("An active account with a verified sign-in email is required.")


def blocked_ids(user):
    outgoing = UserBlock.objects.filter(user=user).values_list("blocked_id", flat=True)
    incoming = UserBlock.objects.filter(blocked=user).values_list("user_id", flat=True)
    return set(outgoing).union(incoming)


def is_blocked(first, second):
    return UserBlock.objects.filter(Q(user=first, blocked=second) | Q(user=second, blocked=first)).exists()


def listing_visible(user, listing, *, own=False):
    require_user(user)
    if listing.owner_id == user.pk:
        return listing
    if own or not listing.owner.is_active or listing.owner.closed_at or not listing.owner.email_verified_at or listing.hidden_at or is_blocked(user, listing.owner):
        raise Http404
    if listing.project.archived_at or not is_project_manager(listing.owner, listing.project):
        raise Http404
    return listing

