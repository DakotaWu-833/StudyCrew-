"""Activate each signed-in user's preferred IANA time zone."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone


class UserTimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        active_zone = None
        if request.user.is_authenticated:
            try:
                active_zone = ZoneInfo(request.user.profile.time_zone)
            except (AttributeError, ZoneInfoNotFoundError):
                active_zone = ZoneInfo("UTC")
        with timezone.override(active_zone):
            return self.get_response(request)
