from django.urls import path

from accounts import views


app_name = "accounts"

urlpatterns = [
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("verify/", views.verify_otp_view, name="verify_otp"),
    path("verify/resend/", views.resend_otp_view, name="resend_otp"),
    path("logout/", views.logout_view, name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("profile/avatar/", views.profile_avatar_view, name="profile_avatar"),
    path("email/change/", views.email_change_view, name="email_change"),
    path("email/change/confirm/", views.email_change_confirm_view, name="email_change_confirm"),
    path("password/change/", views.password_change_view, name="password_change"),
]
