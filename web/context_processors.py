from accounts.policies import is_site_moderator


def navigation_context(request):
    """Keep global template context deliberately small and query-free for visitors."""
    if not request.user.is_authenticated:
        return {"unread_notification_count": 0, "is_site_moderator": False}
    return {
        "unread_notification_count": 0,
        "is_site_moderator": is_site_moderator(request.user),
    }
