"""Session authentication that reports 401 and requires completed MFA."""

from rest_framework import exceptions
from rest_framework.authentication import SessionAuthentication

from accounts.session_security import is_mfa_verified


class MFASessionAuthentication(SessionAuthentication):
    """Keep Django's CSRF enforcement while rejecting pre-MFA sessions."""

    def authenticate_header(self, request) -> str:
        return "Session"

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        if not is_mfa_verified(request._request):
            raise exceptions.AuthenticationFailed("Multi-factor authentication is required.")
        return result
