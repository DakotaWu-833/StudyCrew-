from django.urls import path

from accounts import views, readiness_views


app_name = "accounts"

urlpatterns = [
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("password/reset/", readiness_views.password_reset_request_view, name="password_reset"),
    path("password/reset/confirm/", readiness_views.password_reset_confirm_view, name="password_reset_confirm"),
    path("recovery/", readiness_views.email_recovery_request_view, name="email_recovery"),
    path("recovery/email/verify/", readiness_views.recovery_email_confirm_view, name="recovery_email_confirm"),
    path("recovery/new-email/", readiness_views.email_recovery_new_view, name="email_recovery_new"),
    path("recovery/new-email/confirm/", readiness_views.email_recovery_confirm_view, name="email_recovery_confirm"),
    path("privacy/", readiness_views.privacy_view, name="privacy"),
    path("verify/", views.verify_otp_view, name="verify_otp"),
    path("verify/resend/", views.resend_otp_view, name="resend_otp"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("profile/avatar/", views.profile_avatar_view, name="profile_avatar"),
    path("email/change/", views.email_change_view, name="email_change"),
    path("email/change/confirm/", views.email_change_confirm_view, name="email_change_confirm"),
    path("password/change/", views.password_change_view, name="password_change"),
]
