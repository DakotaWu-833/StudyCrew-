from django.urls import path

from accounts import readiness_api as views

app_name = "account_readiness"

urlpatterns = [
    path("security/", views.AccountSecurityView.as_view(), name="security"),
    path("reauthenticate/", views.ReauthenticateView.as_view(), name="reauthenticate"),
    path("recovery-email/", views.RecoveryAddressView.as_view(), name="recovery_email"),
    path("devices/<uuid:device_id>/revoke/", views.DeviceRevokeView.as_view(), name="device_revoke"),
    path("devices/revoke-others/", views.OtherDevicesRevokeView.as_view(), name="revoke_others"),
    path("data/download/", views.PersonalDataDownloadView.as_view(), name="data_download"),
    path("close/", views.AccountCloseView.as_view(), name="close"),
]
