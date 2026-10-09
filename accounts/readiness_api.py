"""MFA session-authenticated, CSRF-protected account security API."""

from django.contrib.auth import logout
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AccountDeviceSession
from accounts.readiness_selectors import account_security_summary
from accounts.readiness_serializers import CloseAccountSerializer, ReauthenticationSerializer, RecoveryEmailSerializer
from accounts.readiness_services import (
    close_account, personal_data_download, reauthenticate, remove_recovery_email,
    request_recovery_email, require_recent_verification, revoke_all_sessions, revoke_device,
)


class SecureAccountView(APIView):
    # Use the globally configured MFA session authentication without importing
    # the API package into the account domain.
    permission_classes = [IsAuthenticated]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store, private"
        response["Referrer-Policy"] = "no-referrer"
        return response


class AccountSecurityView(SecureAccountView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return Response(account_security_summary(request._request))


class ReauthenticateView(SecureAccountView):
    @extend_schema(request=ReauthenticationSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        serializer = ReauthenticationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reauthenticate(request=request._request, password=serializer.validated_data["current_password"])
        return Response({"message": "Password confirmed for five minutes.", "valid_for_seconds": 300})


class RecoveryAddressView(SecureAccountView):
    @extend_schema(request=RecoveryEmailSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        require_recent_verification(request._request)
        serializer = RecoveryEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_recovery_email(user=request.user, email=serializer.validated_data["email"])
        return Response({"message": "Check the recovery address for a verification link. It expires in 15 minutes."}, status=202)

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def delete(self, request):
        require_recent_verification(request._request)
        remove_recovery_email(user=request.user)
        return Response({"message": "Recovery address removed and outstanding recovery links cancelled."})


class DeviceRevokeView(SecureAccountView):
    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request, device_id):
        require_recent_verification(request._request)
        current = AccountDeviceSession.objects.filter(user=request.user, pk=device_id, session_key=request.session.session_key).exists()
        revoke_device(user=request.user, device_id=device_id)
        if current:
            logout(request._request)
        return Response({"message": "Session signed out.", "signed_out": current})


class OtherDevicesRevokeView(SecureAccountView):
    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        require_recent_verification(request._request)
        revoke_all_sessions(request.user, except_key=request.session.session_key)
        return Response({"message": "Other sessions signed out."})


class PersonalDataDownloadView(SecureAccountView):
    @extend_schema(request=None, responses=OpenApiTypes.BINARY)
    def post(self, request):
        require_recent_verification(request._request)
        response = HttpResponse(personal_data_download(request.user), content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="studycrew-personal-data.json"'
        return response


class AccountCloseView(SecureAccountView):
    @extend_schema(request=CloseAccountSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        require_recent_verification(request._request)
        serializer = CloseAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        close_account(user=request.user, confirmation=serializer.validated_data["confirmation"])
        logout(request._request)
        return Response({"message": "Account closed. Sign-in and project access were revoked. Shared records and immutable audit evidence are retained."})
