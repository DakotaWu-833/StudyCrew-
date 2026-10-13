"""Classic account pages expose the same profile workflows as the workspace."""

import re
import tempfile
from io import BytesIO
from html.parser import HTMLParser

from PIL import Image
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.forms import EmailChangeStartForm
from accounts.models import PendingEmailChange, User
from accounts.session_security import MFA_VERIFIED_SESSION_KEY


class RenderedProfileForm(HTMLParser):
    """Collect successful controls from the actual rendered profile form."""

    def __init__(self):
        super().__init__()
        self.values = {}
        self.in_profile_form = False
        self.select_name = None
        self.textarea_name = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "form":
            self.in_profile_form = attrs.get("action") == reverse("accounts:profile")
        if not self.in_profile_form:
            return
        if tag == "input" and attrs.get("name") and "disabled" not in attrs:
            self.values[attrs["name"]] = attrs.get("value", "")
        elif tag == "select":
            self.select_name = attrs.get("name")
        elif tag == "option" and self.select_name:
            value = attrs.get("value", "")
            self.values.setdefault(self.select_name, value)
            if "selected" in attrs:
                self.values[self.select_name] = value
        elif tag == "textarea":
            self.textarea_name = attrs.get("name")
            self.values[self.textarea_name] = ""

    def handle_data(self, data):
        if self.in_profile_form and self.textarea_name:
            self.values[self.textarea_name] += data

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_profile_form = False
        elif tag == "select":
            self.select_name = None
        elif tag == "textarea":
            self.textarea_name = None


def image_upload():
    output = BytesIO()
    Image.new("RGB", (64, 48), "#4b72d9").save(output, format="PNG")
    return SimpleUploadedFile("avatar.png", output.getvalue(), content_type="image/png")


class EmailChangeStartFormTests(SimpleTestCase):
    def test_current_password_preserves_leading_and_trailing_whitespace(self):
        for password in ("  Strong!Passphrase42", "Strong!Passphrase42  ", "  Strong!Passphrase42  "):
            with self.subTest(password=password):
                form = EmailChangeStartForm(
                    {"new_email": "updated@example.com", "current_password": password}
                )
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["current_password"], password)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ProfileManagementViewTests(TestCase):
    password = "Strong!Passphrase42"

    def setUp(self):
        self.user = User.objects.create_user(
            email="classic@example.com", password=self.password, display_name="Classic Member"
        )
        self.client.force_login(self.user)
        session = self.client.session
        session[MFA_VERIFIED_SESSION_KEY] = timezone.now().isoformat()
        session.save()

    def test_email_change_requires_the_exact_password_including_whitespace(self):
        spaced_password = f"  {self.password}  "
        self.user.set_password(spaced_password)
        self.user.save(update_fields=["password"])
        self.client.force_login(self.user)
        session = self.client.session
        session[MFA_VERIFIED_SESSION_KEY] = timezone.now().isoformat()
        session.save()

        rejected = self.client.post(
            reverse("accounts:email_change"),
            {"new_email": "updated@example.com", "current_password": self.password},
        )
        self.assertEqual(rejected.status_code, 200)
        self.assertContains(rejected, "Check the new address and your current password.")
        self.assertFalse(PendingEmailChange.objects.filter(user=self.user).exists())
        self.assertEqual(len(mail.outbox), 0)

        accepted = self.client.post(
            reverse("accounts:email_change"),
            {"new_email": "updated@example.com", "current_password": spaced_password},
        )
        self.assertRedirects(
            accepted, reverse("accounts:email_change_confirm"), fetch_redirect_response=False
        )
        self.assertEqual(
            PendingEmailChange.objects.get(user=self.user).new_email, "updated@example.com"
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["updated@example.com"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "classic@example.com")

    def test_profile_shows_photo_and_security_action_without_legacy_fields(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Change email")
        self.assertContains(response, "profile-timezone.js")
        self.assertContains(response, "Europe/London")
        self.assertNotContains(response, 'name="email"')
        self.assertNotContains(response, 'name="course_code"')
        self.assertNotContains(response, 'name="avatar_url"')

    def test_editing_rendered_profile_preserves_existing_collaboration_details(self):
        profile = self.user.profile
        profile.major = "Computer Science"
        profile.skills = ["Python", "Research"]
        profile.communication_languages = ["English", "Mandarin"]
        profile.collaboration_preference = "hybrid"
        profile.save()

        response = self.client.get(reverse("accounts:profile"))
        controls = RenderedProfileForm()
        controls.feed(response.content.decode())
        for field in ("major", "skills", "communication_languages", "collaboration_preference"):
            self.assertIn(field, controls.values, f"The profile page must submit its current {field} value.")
        controls.values["display_name"] = "Updated Classic Member"
        saved = self.client.post(reverse("accounts:profile"), controls.values)
        self.assertRedirects(saved, reverse("accounts:profile"), fetch_redirect_response=False)

        profile.refresh_from_db()
        self.assertEqual(profile.display_name, "Updated Classic Member")
        self.assertEqual(profile.major, "Computer Science")
        self.assertEqual(profile.skills, ["Python", "Research"])
        self.assertEqual(profile.communication_languages, ["English", "Mandarin"])
        self.assertEqual(profile.collaboration_preference, "hybrid")

    def test_photo_upload_and_email_rebinding(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            uploaded = self.client.post(
                reverse("accounts:profile_avatar"), {"avatar": image_upload()}
            )
            self.assertRedirects(uploaded, reverse("accounts:profile"), fetch_redirect_response=False)
            profile = self.client.get(reverse("accounts:profile"))
            self.assertContains(profile, reverse("api:user-avatar", args=[self.user.pk]))

        started = self.client.post(
            reverse("accounts:email_change"),
            {"new_email": "updated@example.com", "current_password": self.password},
        )
        self.assertRedirects(started, reverse("accounts:email_change_confirm"), fetch_redirect_response=False)
        self.assertEqual(mail.outbox[0].to, ["updated@example.com"])
        code = re.search(r"\b\d{6}\b", mail.outbox[0].body).group()
        confirmed = self.client.post(reverse("accounts:email_change_confirm"), {"code": code})
        self.assertRedirects(confirmed, reverse("accounts:profile"), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "updated@example.com")
