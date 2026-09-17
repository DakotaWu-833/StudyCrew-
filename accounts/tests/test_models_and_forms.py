from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from accounts.forms import ProfileForm, RegistrationForm
from accounts.models import Profile, User
from accounts.services import throttle_digest
from accounts.tests.helpers import VALID_PASSWORD


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class UserModelTests(TestCase):
    def test_manager_creates_uuid_email_user_and_exactly_one_profile(self):
        user = User.objects.create_user(
            email="  Student@EXAMPLE.COM ",
            password=VALID_PASSWORD,
            display_name="Study Student",
        )

        self.assertIsInstance(user.pk, UUID)
        self.assertEqual(user.email, "student@example.com")
        self.assertNotEqual(user.password, VALID_PASSWORD)
        self.assertTrue(user.check_password(VALID_PASSWORD))
        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.email_verified_at)
        self.assertEqual(Profile.objects.filter(user=user).count(), 1)
        self.assertEqual(user.profile.display_name, "Study Student")

    def test_manager_rejects_invalid_profile_without_partial_user(self):
        with self.assertRaises(ValidationError):
            User.objects.create_user(
                email="invalid-profile@example.com",
                password=VALID_PASSWORD,
                display_name="X",
            )

        self.assertFalse(User.objects.filter(email="invalid-profile@example.com").exists())

    def test_case_variants_cannot_create_duplicate_email(self):
        User.objects.create_user(email="member@example.com", password=VALID_PASSWORD)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(email="MEMBER@example.com", password=VALID_PASSWORD)

    def test_superuser_contract_is_enforced(self):
        user = User.objects.create_superuser(email="admin@example.com", password=VALID_PASSWORD)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_active)
        with self.assertRaisesMessage(ValueError, "is_staff=True"):
            User.objects.create_superuser(
                email="invalid-admin@example.com",
                password=VALID_PASSWORD,
                is_staff=False,
            )

    def test_throttle_digest_is_stable_keyed_and_contains_no_raw_identifier(self):
        digest = throttle_digest("account", "private@example.com")
        self.assertEqual(digest, throttle_digest("account", "private@example.com"))
        self.assertEqual(len(digest), 64)
        self.assertNotIn("private", digest)
        self.assertNotIn("example", digest)


class AccountFormTests(TestCase):
    def test_registration_enforces_full_password_policy(self):
        form = RegistrationForm(
            data={
                "email": "person@example.com",
                "display_name": "Person",
                "password1": "alllowercase123",
                "password2": "alllowercase123",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("password1", form.errors)

    def test_registration_rejects_password_mismatch(self):
        form = RegistrationForm(
            data={
                "email": "person@example.com",
                "display_name": "Person",
                "password1": VALID_PASSWORD,
                "password2": "DifferentPass!234",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_registration_does_not_expose_email_uniqueness(self):
        User.objects.create_user(email="person@example.com", password=VALID_PASSWORD)
        form = RegistrationForm(
            data={
                "email": "PERSON@example.com",
                "display_name": "Person",
                "password1": VALID_PASSWORD,
                "password2": VALID_PASSWORD,
            }
        )
        self.assertTrue(form.is_valid())

    def test_profile_form_accepts_iana_zone_and_rejects_file_like_value(self):
        user = User.objects.create_user(email="zone@example.com", password=VALID_PASSWORD)
        valid = ProfileForm(
            data={
                "display_name": "Zone User",
                "course_code": "ELEC3609",
                "time_zone": "Australia/Sydney",
                "biography": "Coordinates a project team.",
                "avatar_url": "https://example.com/avatar.png",
            },
            instance=user.profile,
        )
        self.assertTrue(valid.is_valid(), valid.errors)

        invalid = ProfileForm(
            data={
                "display_name": "Zone User",
                "course_code": "",
                "time_zone": "../../etc/passwd",
                "biography": "",
                "avatar_url": "",
            },
            instance=user.profile,
        )
        self.assertFalse(invalid.is_valid())
        self.assertIn("time_zone", invalid.errors)

    def test_profile_model_timezone_validator_is_available_for_non_form_writes(self):
        user = User.objects.create_user(email="model-zone@example.com", password=VALID_PASSWORD)
        user.profile.time_zone = "Mars/Olympus_Mons"
        with self.assertRaises(ValidationError):
            user.profile.full_clean()
