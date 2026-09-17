"""Account-level role checks shared by web and API presentation layers."""

from django.core.exceptions import PermissionDenied


def is_site_moderator(user) -> bool:
    """Return whether the user has the complete, least-privilege moderator role."""

    return bool(
        getattr(user, "is_authenticated", False)
        and user.is_active
        and user.is_staff
        and user.has_perm("tasks.moderate_reports")
        and user.has_perm("accounts.manage_user_status")
    )


def require_site_moderator(user) -> None:
    if not is_site_moderator(user):
        raise PermissionDenied("Site moderator permission is required.")
