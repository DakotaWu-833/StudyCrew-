"""Profile media and sign-in-address changes stay scoped to the current user."""

import re
import tempfile
from io import BytesIO
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import quote

from PIL import Image
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from accounts.models import PendingEmailChange
from accounts.models import Profile
from accounts.profile_services import MAX_AVATAR_BYTES
from api.tests.base import APIDomainTestCase
from projects.models import ProjectMembership


def image_upload(*, format="PNG", name="avatar.png"):
    output = BytesIO()
    Image.new("RGB", (64, 48), "#4b72d9").save(output, format=format)
    return SimpleUploadedFile(name, output.getvalue(), content_type="image/png")


class ProfileManagementAPITests(APIDomainTestCase):
    def test_global_time_zones_include_current_gmt_offsets(self):
        self.authenticate()
        response = self.client.get("/api/v1/time-zones/")
        self.assertEqual(response.status_code, 200)
        values = {entry["value"]: entry for entry in response.json()["results"]}
        self.assertGreater(len(values), 300)
        for zone in ("Australia/Sydney", "Europe/London", "America/New_York", "Asia/Tokyo"):
            self.assertIn(zone, values)
            self.assertRegex(values[zone]["offset"], r"^GMT[+-]\d{2}:\d{2}$")
            self.assertIn(values[zone]["offset"], values[zone]["label"])

    def test_avatar_upload_reencodes_and_limits_access(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.authenticate(self.owner)
            response = self.client.post(
                "/api/v1/profile/avatar/", {"avatar": image_upload()}, format="multipart"
            )
            self.assertEqual(response.status_code, 200, response.content)
            avatar_url = response.json()["avatar_image_url"]
            self.assertTrue(avatar_url.endswith(f"/users/{self.owner.pk}/avatar/"))
            own_image = self.client.get(avatar_url)
            self.assertEqual(own_image.status_code, 200)
            self.assertEqual(own_image["Content-Type"], "image/jpeg")
            self.assertEqual(own_image["Cache-Control"], "private, no-store")
            with Image.open(BytesIO(b"".join(own_image.streaming_content))) as rendered:
                self.assertEqual(rendered.size, (512, 512))
                self.assertEqual(rendered.format, "JPEG")
            own_image.close()

            self.authenticate(self.member)
            teammate_image = self.client.get(avatar_url)
            self.assertEqual(teammate_image.status_code, 200)
            teammate_image.close()
            self.authenticate(self.outsider)
            self.assertEqual(self.client.get(avatar_url).status_code, 403)

    def test_avatar_rejects_bad_format_without_replacing_current_image(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.authenticate(self.owner)
            good = self.client.post("/api/v1/profile/avatar/", {"avatar": image_upload()}, format="multipart")
            self.assertEqual(good.status_code, 200)
            original_name = Profile.objects.get(user=self.owner).avatar.name
            bad = self.client.post(
                "/api/v1/profile/avatar/",
                {"avatar": SimpleUploadedFile("fake.png", b"<svg>not an image</svg>", content_type="image/png")},
                format="multipart",
            )
            self.assertEqual(bad.status_code, 400)
            self.assertEqual(Profile.objects.get(user=self.owner).avatar.name, original_name)

    def test_avatar_accepts_exact_two_mib_file_and_rejects_any_larger_file(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.authenticate(self.owner)
            encoded = image_upload().read()
            content = encoded + b"\0" * (MAX_AVATAR_BYTES - len(encoded))
            accepted = self.client.post(
                "/api/v1/profile/avatar/",
                {"avatar": SimpleUploadedFile("full-size.png", content, content_type="image/png")},
                format="multipart",
            )
            self.assertEqual(accepted.status_code, 200, accepted.content)
            original_name = Profile.objects.get(user=self.owner).avatar.name
            self.assertTrue(original_name.endswith(".jpg"))
            rejected = self.client.post(
                "/api/v1/profile/avatar/",
                {"avatar": SimpleUploadedFile("too-large.png", content + b"\0", content_type="image/png")},
                format="multipart",
            )
            self.assertEqual(rejected.status_code, 400)
            self.assertEqual(Profile.objects.get(user=self.owner).avatar.name, original_name)

    @override_settings(USE_X_ACCEL_REDIRECT=True)
    def test_production_avatar_handoff_is_private_and_quotes_storage_key(self):
        avatar_name = "avatars/private photo \u6d4b\u8bd5#%.jpg"
        Profile.objects.filter(user=self.owner).update(avatar=avatar_name)
        avatar_url = f"/api/v1/users/{self.owner.pk}/avatar/"
        # Production authorization delegates bytes to Nginx; Django must not open the file.
        with patch("django.db.models.fields.files.FieldFile.open") as open_file:
            for actor in (self.owner, self.member):
                with self.subTest(actor=actor.pk):
                    self.authenticate(actor)
                    response = self.client.get(avatar_url)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.content, b"")
                    self.assertFalse(response.streaming)
                    self.assertEqual(response["Content-Type"], "image/jpeg")
                    self.assertEqual(response["Cache-Control"], "private, no-store")
                    self.assertEqual(
                        response["X-Accel-Redirect"], f"/protected-media/{quote(avatar_name, safe='/')}"
                    )
            open_file.assert_not_called()

    @override_settings(USE_X_ACCEL_REDIRECT=True)
    def test_production_avatar_handoff_is_never_exposed_without_current_access(self):
        Profile.objects.filter(user=self.owner).update(avatar="avatars/private.jpg")
        avatar_url = f"/api/v1/users/{self.owner.pk}/avatar/"
        self.authenticate(self.outsider)
        outsider = self.client.get(avatar_url)
        self.assertEqual(outsider.status_code, 403)
        self.assertNotIn("X-Accel-Redirect", outsider)

        ProjectMembership.objects.filter(project=self.project, user=self.member).update(
            removed_at=timezone.now()
        )
        self.authenticate(self.member)
        removed_member = self.client.get(avatar_url)
        self.assertEqual(removed_member.status_code, 403)
        self.assertNotIn("X-Accel-Redirect", removed_member)

        self.client.logout()
        anonymous = self.client.get(avatar_url)
        self.assertEqual(anonymous.status_code, 401)
        self.assertNotIn("X-Accel-Redirect", anonymous)

        self.client.force_login(self.owner)
        before_mfa = self.client.get(avatar_url)
        self.assertEqual(before_mfa.status_code, 401)
        self.assertNotIn("X-Accel-Redirect", before_mfa)

        self.authenticate(self.owner)
        Profile.objects.filter(user=self.owner).update(avatar="")
        missing_image = self.client.get(avatar_url)
        self.assertEqual(missing_image.status_code, 404)
        self.assertNotIn("X-Accel-Redirect", missing_image)

    def test_email_change_requires_password_and_new_address_code_then_is_one_use(self):
        self.authenticate(self.owner)
        wrong = self.client.post(
            "/api/v1/account/email-change/request/",
            {"new_email": "new-owner@example.com", "current_password": "wrong"},
            format="json",
        )
        self.assertEqual(wrong.status_code, 400)
        self.assertFalse(PendingEmailChange.objects.filter(user=self.owner).exists())

        started = self.client.post(
            "/api/v1/account/email-change/request/",
            {"new_email": "new-owner@example.com", "current_password": self.password},
            format="json",
        )
        self.assertEqual(started.status_code, 201, started.content)
        self.assertEqual([message.to for message in mail.outbox], [["new-owner@example.com"]])
        code = re.search(r"\b\d{6}\b", mail.outbox[0].body).group()
        request_id = started.json()["request_id"]

        incorrect = self.client.post(
            "/api/v1/account/email-change/confirm/",
            {"request_id": request_id, "code": "000000" if code != "000000" else "999999"},
            format="json",
        )
        self.assertEqual(incorrect.status_code, 400)
        self.assertEqual(PendingEmailChange.objects.get(user=self.owner).attempt_count, 1)

        confirmed = self.client.post(
            "/api/v1/account/email-change/confirm/",
            {"request_id": request_id, "code": code},
            format="json",
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.content)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.email, "new-owner@example.com")
        self.assertIsNotNone(self.owner.email_verified_at)
        self.assertEqual(mail.outbox[-1].to, ["api-owner@example.com"])
        self.assertFalse(PendingEmailChange.objects.filter(user=self.owner).exists())
        replay = self.client.post(
            "/api/v1/account/email-change/confirm/",
            {"request_id": request_id, "code": code},
            format="json",
        )
        self.assertEqual(replay.status_code, 400)

    def test_email_change_does_not_expose_code_or_allow_existing_address(self):
        self.authenticate(self.owner)
        taken = self.client.post(
            "/api/v1/account/email-change/request/",
            {"new_email": self.member.email, "current_password": self.password},
            format="json",
        )
        self.assertEqual(taken.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)
        started = self.client.post(
            "/api/v1/account/email-change/request/",
            {"new_email": "fresh@example.com", "current_password": self.password},
            format="json",
        )
        self.assertEqual(started.status_code, 201)
        self.assertNotIn("code", started.json())
        too_soon = self.client.post(
            "/api/v1/account/email-change/request/",
            {"new_email": "another@example.com", "current_password": self.password},
            format="json",
        )
        self.assertEqual(too_soon.status_code, 400)
        self.assertEqual(len(mail.outbox), 1)

    def test_email_change_expired_or_exhausted_code_keeps_original_address(self):
        self.authenticate(self.owner)
        started = self.client.post(
            "/api/v1/account/email-change/request/",
            {"new_email": "fresh@example.com", "current_password": self.password},
            format="json",
        )
        self.assertEqual(started.status_code, 201)
        request_id = started.json()["request_id"]
        code = re.search(r"\b\d{6}\b", mail.outbox[0].body).group()
        pending = PendingEmailChange.objects.get(user=self.owner)
        pending.expires_at = timezone.now() - timedelta(seconds=1)
        pending.save(update_fields=("expires_at",))
        expired = self.client.post(
            "/api/v1/account/email-change/confirm/",
            {"request_id": request_id, "code": code},
            format="json",
        )
        self.assertEqual(expired.status_code, 400)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.email, "api-owner@example.com")
        self.assertFalse(PendingEmailChange.objects.filter(user=self.owner).exists())
