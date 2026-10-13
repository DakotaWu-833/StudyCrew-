"""Public recovery forms: GET only displays; CSRF protected POST consumes links."""

from django.contrib import messages
from django.contrib.auth import logout
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from accounts.readiness_forms import (
    EmailRecoveryRequestForm, RecoveredEmailForm, ResetPasswordForm, ResetRequestForm, SecurityLinkForm,
)
from accounts.readiness_services import (
    GENERIC_RECOVERY_MESSAGE, PRIVACY_NOTICE, confirm_recovery_email,
    finish_recovered_signin_email, request_email_recovery, request_password_reset,
    reset_password, start_recovered_signin_email,
)
from accounts.services import client_ip


def _page(request, *, form, title, description, button, request_page=False):
    response = render(request, "accounts/security_link.html", {
        "form": form, "title": title, "description": description, "button": button, "request_page": request_page,
    })
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "no-store, private"
    return response


@never_cache
@require_http_methods(["GET", "POST"])
def password_reset_request_view(request):
    form = ResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        request_password_reset(email=form.cleaned_data["email"], ip_address=client_ip(request))
        messages.success(request, GENERIC_RECOVERY_MESSAGE)
        return redirect("accounts:password_reset")
    return _page(request, form=form, title="Reset your password",
                 description="Enter your sign-in email. We will send a single-use security link if the account is eligible.",
                 button="Request reset link", request_page=True)


@never_cache
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("new_password", "confirm_password", "token")
def password_reset_confirm_view(request):
    form = ResetPasswordForm(request.POST or None, initial={"token": request.GET.get("token", "")})
    if request.method == "POST" and form.is_valid():
        try:
            reset_password(token=form.cleaned_data["token"], new_password=form.cleaned_data["new_password"])
        except ValidationError as error:
            form.add_error(None, " ".join(error.messages))
        else:
            logout(request)
            messages.success(request, "Password reset. All sessions were signed out. Sign in and complete email verification.")
            return redirect("accounts:login")
    return _page(request, form=form, title="Choose a new password",
                 description="This link expires after 15 minutes and can be used once. All signed-in sessions will be revoked.",
                 button="Reset password")


@never_cache
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("password")
def email_recovery_request_view(request):
    form = EmailRecoveryRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        request_email_recovery(email=form.cleaned_data["email"], password=form.cleaned_data["password"], ip_address=client_ip(request))
        messages.success(request, GENERIC_RECOVERY_MESSAGE)
        return redirect("accounts:email_recovery")
    return _page(request, form=form, title="Recover an unavailable sign-in email",
                 description=("Enter your old sign-in email and current password. We will send a link to your previously verified recovery address. "
                              "You will then verify a new sign-in email. If you have lost both your password and sign-in mailbox, or did not set a recovery address, contact support; automatic recovery is unavailable."),
                 button="Send recovery link", request_page=True)


@never_cache
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("token")
def recovery_email_confirm_view(request):
    form = SecurityLinkForm(request.POST or None, initial={"token": request.GET.get("token", "")})
    if request.method == "POST" and form.is_valid():
        try:
            confirm_recovery_email(token=form.cleaned_data["token"])
        except ValidationError as error:
            form.add_error(None, " ".join(error.messages))
        else:
            messages.success(request, "Recovery email verified. You can review it in Account security.")
            return redirect("accounts:login")
    return _page(request, form=form, title="Verify your recovery address",
                 description="Confirm you own this address. It will be used only for account recovery after your password has been verified.",
                 button="Verify recovery email")


@never_cache
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("token")
def email_recovery_new_view(request):
    form = RecoveredEmailForm(request.POST or None, initial={"token": request.GET.get("token", "")})
    if request.method == "POST" and form.is_valid():
        try:
            start_recovered_signin_email(token=form.cleaned_data["token"], new_email=form.cleaned_data["new_email"])
        except ValidationError as error:
            form.add_error(None, " ".join(error.messages))
        else:
            messages.success(request, "Check your new sign-in mailbox for a confirmation link. Your sign-in address changes only after you confirm it.")
            return redirect("accounts:login")
    return _page(request, form=form, title="Choose your new sign-in address",
                 description="Your recovery mailbox has the security link. The new sign-in address must also be verified before it replaces your old address.",
                 button="Send new-address verification")


@never_cache
@require_http_methods(["GET", "POST"])
@sensitive_post_parameters("token")
def email_recovery_confirm_view(request):
    form = SecurityLinkForm(request.POST or None, initial={"token": request.GET.get("token", "")})
    if request.method == "POST" and form.is_valid():
        try:
            finish_recovered_signin_email(token=form.cleaned_data["token"])
        except ValidationError as error:
            form.add_error(None, " ".join(error.messages))
        else:
            logout(request)
            messages.success(request, "New sign-in address verified. All sessions were signed out. Sign in using the new email and your password.")
            return redirect("accounts:login")
    return _page(request, form=form, title="Confirm your new sign-in address",
                 description="Confirm this address to complete recovery and revoke all existing sessions. You will still need your password and email verification to sign in.",
                 button="Confirm new sign-in email")


@never_cache
@require_http_methods(["GET"])
def privacy_view(request):
    return render(request, "accounts/privacy.html", {"privacy": PRIVACY_NOTICE})
