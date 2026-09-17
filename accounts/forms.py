"""Forms for the server-rendered account and authentication flows."""

from __future__ import annotations

from zoneinfo import available_timezones

from django import forms
from django.contrib.auth.forms import PasswordChangeForm as DjangoPasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from accounts.models import Profile, User


class RegistrationForm(forms.Form):
    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(
            attrs={"autocomplete": "email", "autocapitalize": "none", "spellcheck": "false"}
        ),
    )
    display_name = forms.CharField(
        min_length=2,
        max_length=80,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        help_text=(
            "Use at least 12 characters, including uppercase, lowercase, a number, and a symbol."
        ),
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_email(self) -> str:
        # Uniqueness is deliberately checked only in the service so the form
        # cannot be used as an account-enumeration oracle.
        return User.objects.normalize_email(self.cleaned_data["email"]).strip().lower()

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The two password entries do not match.")

        if password1:
            candidate = User(email=cleaned_data.get("email", ""))
            try:
                validate_password(password1, user=candidate)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned_data


class LoginForm(forms.Form):
    email = forms.EmailField(
        max_length=254,
        widget=forms.EmailInput(
            attrs={"autocomplete": "email", "autocapitalize": "none", "spellcheck": "false"}
        ),
    )
    password = forms.CharField(
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    next = forms.CharField(required=False, widget=forms.HiddenInput())

    def clean_email(self) -> str:
        return User.objects.normalize_email(self.cleaned_data["email"]).strip().lower()


class OTPVerificationForm(forms.Form):
    code = forms.RegexField(
        regex=r"^\d{6}$",
        label="Six-digit code",
        error_messages={"invalid": "Enter the six-digit code from your email."},
        widget=forms.TextInput(
            attrs={
                "autocomplete": "one-time-code",
                "inputmode": "numeric",
                "pattern": "[0-9]{6}",
                "maxlength": "6",
                "placeholder": "000000",
            }
        ),
    )


class ProfileForm(forms.ModelForm):
    time_zone = forms.ChoiceField(
        choices=((zone, zone) for zone in sorted(available_timezones())),
        help_text="Meeting times will be displayed in this IANA time zone.",
    )

    class Meta:
        model = Profile
        fields = ("display_name", "course_code", "time_zone", "biography", "avatar_url")
        widgets = {
            "display_name": forms.TextInput(attrs={"autocomplete": "name"}),
            "course_code": forms.TextInput(attrs={"autocomplete": "off"}),
            "biography": forms.Textarea(attrs={"rows": 5}),
            "avatar_url": forms.URLInput(attrs={"autocomplete": "url"}),
        }


class PasswordChangeForm(DjangoPasswordChangeForm):
    """Django's secure password-change flow with explicit autocomplete hints."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["old_password"].widget.attrs["autocomplete"] = "current-password"
        self.fields["new_password1"].widget.attrs["autocomplete"] = "new-password"
        self.fields["new_password2"].widget.attrs["autocomplete"] = "new-password"
