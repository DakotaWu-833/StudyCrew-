from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from accounts.management.commands.seed_demo import DEMO_USERS, strong_random_password
from activity.models import ActivityEvent
from meetings.models import Meeting, MeetingAttendance
from projects.models import Project, ProjectInvitation, ProjectMembership
from tasks.models import Task, TaskComment


GENERATED_PASSWORDS = (
    "OwnerSeed!Passphrase01Aa",
    "FacilitatorSeed!Pass02Bb",
    "MemberSeed!Passphrase03Cc",
    "ResearcherSeed!Password04Dd",
)


class SeedDemoCommandTests(TestCase):
    def snapshot_counts(self):
        return {
            "users": get_user_model().objects.count(),
            "projects": Project.objects.count(),
            "memberships": ProjectMembership.objects.count(),
            "invitations": ProjectInvitation.objects.count(),
            "tasks": Task.objects.count(),
            "comments": TaskComment.objects.count(),
            "meetings": Meeting.objects.count(),
            "attendance": MeetingAttendance.objects.count(),
            "events": ActivityEvent.objects.count(),
        }

    @patch(
        "accounts.management.commands.seed_demo.strong_random_password",
        side_effect=GENERATED_PASSWORDS,
    )
    def test_seed_is_idempotent_and_credentials_are_only_shown_on_creation(self, random_password):
        first_output = StringIO()
        call_command("seed_demo", stdout=first_output)
        first_counts = self.snapshot_counts()

        self.assertEqual(get_user_model().objects.filter(email__in=[u[0] for u in DEMO_USERS]).count(), 4)
        for (email, _display_name, _course_code), password in zip(DEMO_USERS, GENERATED_PASSWORDS):
            user = get_user_model().objects.get(email=email)
            self.assertNotEqual(user.password, password)
            self.assertTrue(user.check_password(password))
            self.assertIn(password, first_output.getvalue())

        second_output = StringIO()
        call_command("seed_demo", stdout=second_output)
        self.assertEqual(self.snapshot_counts(), first_counts)
        self.assertIn("Existing passwords were preserved", second_output.getvalue())
        for password in GENERATED_PASSWORDS:
            self.assertNotIn(password, second_output.getvalue())
        self.assertEqual(random_password.call_count, 4)

    @patch(
        "accounts.management.commands.seed_demo.strong_random_password",
        side_effect=GENERATED_PASSWORDS + tuple(f"ResetSeed!Passphrase{i}Xx" for i in range(4)),
    )
    def test_reset_rotates_passwords_and_repairs_demo_profile_fields(self, _random_password):
        call_command("seed_demo", stdout=StringIO())
        owner = get_user_model().objects.get(email=DEMO_USERS[0][0])
        owner.profile.display_name = "Changed Name"
        owner.profile.course_code = "OTHER"
        owner.profile.save()

        output = StringIO()
        call_command("seed_demo", reset_passwords=True, stdout=output)
        owner.refresh_from_db()
        owner.profile.refresh_from_db()
        self.assertEqual(owner.profile.display_name, DEMO_USERS[0][1])
        self.assertEqual(owner.profile.course_code, DEMO_USERS[0][2])
        self.assertTrue(owner.check_password("ResetSeed!Passphrase0Xx"))
        self.assertIn("ResetSeed!Passphrase0Xx", output.getvalue())

    def test_generated_password_has_required_character_classes(self):
        password = strong_random_password()
        self.assertEqual(len(password), 20)
        self.assertTrue(any(character.isupper() for character in password))
        self.assertTrue(any(character.islower() for character in password))
        self.assertTrue(any(character.isdigit() for character in password))
        self.assertTrue(any(character in "!@#$%^&*" for character in password))
