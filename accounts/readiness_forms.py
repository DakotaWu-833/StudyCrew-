from django import forms


class ResetRequestForm(forms.Form):
    email = forms.EmailField(label="Sign-in email", max_length=254, widget=forms.EmailInput(attrs={"autocomplete": "email"}))


class ResetPasswordForm(forms.Form):
    token = forms.CharField(max_length=128, widget=forms.HiddenInput)
    new_password = forms.CharField(label="New password", strip=False, max_length=512,
                                   help_text="Use at least 12 characters, including uppercase, lowercase, a number and a symbol.",
                                   widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    confirm_password = forms.CharField(label="Confirm new password", strip=False, max_length=512,
                                       widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean(self):
        data = super().clean()
        if data.get("new_password") != data.get("confirm_password"):
            self.add_error("confirm_password", "The passwords do not match.")
        return data


class EmailRecoveryRequestForm(ResetRequestForm):
    password = forms.CharField(label="Current password", strip=False, max_length=512,
                               widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class SecurityLinkForm(forms.Form):
    token = forms.CharField(max_length=128, widget=forms.HiddenInput)


class RecoveredEmailForm(SecurityLinkForm):
    new_email = forms.EmailField(label="New sign-in email", max_length=254,
                                 widget=forms.EmailInput(attrs={"autocomplete": "email"}))
