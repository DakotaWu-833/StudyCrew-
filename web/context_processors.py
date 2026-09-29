from django.conf import settings

from accounts.policies import is_site_moderator


def _asset_version(filename):
    try:
        return str((settings.BASE_DIR / "static" / filename).stat().st_mtime_ns)
    except OSError:
        return "0"


def navigation_context(request):
    """Keep global template context deliberately small and query-free for visitors."""
    if not request.user.is_authenticated:
        return {"unread_notification_count": 0, "is_site_moderator": False}
    return {
        "unread_notification_count": 0,
        "is_site_moderator": is_site_moderator(request.user),
    }


def site_asset_versions(_request):
    """Bust browser caches when the small server-rendered site assets change."""
    return {
        "site_css_version": _asset_version("css/app.css"),
        "site_js_version": _asset_version("js/site.js"),
    }
