"""Server-rendered account views backed by explicit transactional services."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from accounts.forms import (
    LoginForm,
    OTPVerificationForm,
    PasswordChangeForm,
    ProfileForm,
    RegistrationForm,
)
from accounts.models import EmailOTPChallenge, Profile
from accounts.session_security import mark_mfa_verified
from accounts.services import (
    OTPUnavailable,
    RegistrationUnavailable,
    SignInUnavailable,
    client_ip,
    register_user,
    resend_otp,
    start_password_login,
    verify_otp,
)


OTP_CHALLENGE_SESSION_KEY = "accounts.otp_challenge_id"
OTP_PURPOSE_SESSION_KEY = "accounts.otp_purpose"
LOGIN_NEXT_SESSION_KEY = "accounts.login_next"

GENERIC_SIGN_IN_ERROR = (
    "The email or password is incorrect, or sign-in is temporarily unavailable."
)
GENERIC_OTP_ERROR = "The code is invalid or no longer available. Restart sign-in if needed."
GENERIC_REGISTRATION_ERROR = (
    "We could not create that account. Sign in if you already registered, or try again later."
)


def _safe_next_url(request: HttpRequest, candidate: str | None) -> str:
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return reverse("web:dashboard")


def _store_challenge(request: HttpRequest, challenge: EmailOTPChallenge) -> None:
    request.session[OTP_CHALLENGE_SESSION_KEY] = str(challenge.id)
    request.session[OTP_PURPOSE_SESSION_KEY] = challenge.purpose


def _clear_challenge(request: HttpRequest) -> None:
    request.session.pop(OTP_CHALLENGE_SESSION_KEY, None)
    request.session.pop(OTP_PURPOSE_SESSION_KEY, None)


def _current_challenge(request: HttpRequest) -> EmailOTPChallenge | None:
    challenge_id = request.session.get(OTP_CHALLENGE_SESSION_KEY)
    purpose = request.session.get(OTP_PURPOSE_SESSION_KEY)
    if not challenge_id or purpose not in EmailOTPChallenge.Purpose.values:
        return None
    try:
        return (
            EmailOTPChallenge.objects.select_related("user")
            .filter(id=challenge_id, purpose=purpose)
            .first()
        )
    except (TypeError, ValueError, ValidationError):
        # Session data is untrusted input and must not turn into a server error.
        return None


def _masked_email(email: str) -> str:
    local, separator, domain = email.partition("@")
    if not separator:
        return "your email address"
    visible = local[:1] if local else ""
    return f"{visible}{'•' * max(3, len(local) - 1)}@{domain}"


@never_cache
@sensitive_post_parameters("password1", "password2")
def register_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("web:dashboard")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            result = register_user(
                email=form.cleaned_data["email"],
                display_name=form.cleaned_data["display_name"],
                password=form.cleaned_data["password1"],
            )
        except RegistrationUnavailable:
            form.add_error(None, GENERIC_REGISTRATION_ERROR)
        else:
            _store_challenge(request, result.challenge)
            if result.delivered:
                messages.success(request, "We sent a six-digit verification code to your email.")
            else:
                messages.error(
                    request,
                    "The code could not be delivered. You can safely try resending it.",
                )
            return redirect("accounts:verify_otp")
    return render(request, "accounts/register.html", {"form": form})


@never_cache
@sensitive_post_parameters("password")
def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("web:dashboard")

    initial_next = _safe_next_url(request, request.GET.get("next"))
    form = LoginForm(request.POST or None, initial={"next": initial_next})
    if request.method == "POST" and form.is_valid():
        try:
            result = start_password_login(
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
                ip_address=client_ip(request),
            )
        except SignInUnavailable:
            form.add_error(None, GENERIC_SIGN_IN_ERROR)
        else:
            _store_challenge(request, result.challenge)
            request.session[LOGIN_NEXT_SESSION_KEY] = _safe_next_url(
                request, form.cleaned_data.get("next")
            )
            if result.delivered:
                messages.success(request, "We sent a six-digit security code to your email.")
            else:
                messages.error(
                    request,
                    "The code could not be delivered. You can safely try resending it.",
                )
            return redirect("accounts:verify_otp")
    return render(request, "accounts/login.html", {"form": form})


@never_cache
@sensitive_post_parameters("code")
def verify_otp_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("web:dashboard")

    challenge = _current_challenge(request)
    if challenge is None:
        _clear_challenge(request)
        messages.error(request, "Start sign-in or registration to request a new code.")
        return redirect("accounts:login")

    form = OTPVerificationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = verify_otp(
                challenge_id=str(challenge.id),
                purpose=challenge.purpose,
                code=form.cleaned_data["code"],
            )
        except OTPUnavailable:
            form.add_error(None, GENERIC_OTP_ERROR)
        else:
            purpose = challenge.purpose
            next_url = _safe_next_url(request, request.session.pop(LOGIN_NEXT_SESSION_KEY, None))
            _clear_challenge(request)
            auth_login(
                request,
                user,
                backend="django.contrib.auth.backends.ModelBackend",
            )
            mark_mfa_verified(request)
            if purpose == EmailOTPChallenge.Purpose.REGISTRATION:
                messages.success(request, "Your email is verified and your account is ready.")
            else:
                messages.success(request, "You are now signed in.")
            return redirect(next_url)

    return render(
        request,
        "accounts/verify_otp.html",
        {
            "form": form,
            "purpose": challenge.purpose,
            "masked_email": _masked_email(challenge.user.email),
        },
    )


@require_POST
def resend_otp_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("web:dashboard")

    challenge = _current_challenge(request)
    if challenge is None:
        _clear_challenge(request)
        messages.error(request, "Start sign-in or registration to request a new code.")
        return redirect("accounts:login")

    try:
        result = resend_otp(
            challenge_id=str(challenge.id),
            purpose=challenge.purpose,
        )
    except OTPUnavailable:
        messages.error(
            request,
            "A new code is not available yet. Wait before trying again or restart sign-in.",
        )
    else:
        _store_challenge(request, result.challenge)
        if result.delivered:
            messages.success(request, "A new six-digit code was sent.")
        else:
            messages.error(request, "The new code could not be delivered. Try again later.")
    return redirect("accounts:verify_otp")


@require_POST
@login_required
def logout_view(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("web:home")


@login_required
def profile_view(request: HttpRequest) -> HttpResponse:
    profile = get_object_or_404(Profile, user=request.user)
    form = ProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile was updated.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})


@never_cache
@sensitive_post_parameters("old_password", "new_password1", "new_password2")
@login_required
def password_change_view(request: HttpRequest) -> HttpResponse:
    form = PasswordChangeForm(user=request.user, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        # Rotate the current session and update only its auth hash. Other active
        # sessions retain the old hash and are rejected on their next request.
        update_session_auth_hash(request, user)
        messages.success(request, "Your password was changed securely.")
        return redirect("accounts:profile")
    return render(request, "accounts/password_change.html", {"form": form})
