"""Account recovery never skips verification, leaks tokens or deletes evidence."""

import json
import re
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.sessions.models import Session
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import AccountDeviceSession, AccountSecurityToken, EmailOTPChallenge, RecoveryEmail, User
from accounts.readiness_services import (
    close_account, confirm_recovery_email, finish_recovered_signin_email,
    personal_data_download, remove_recovery_email, request_email_recovery,
    request_password_reset, request_recovery_email, reset_password,
    revoke_all_sessions, start_recovered_signin_email,
)
from accounts.tests.helpers import NEW_VALID_PASSWORD, VALID_PASSWORD
from activity.models import ActivityEvent
from projects.models import Project, ProjectInvitation, ProjectMembership
from tasks.models import Task, TaskAssignment, TaskComment


def latest_token():
    link = re.search(r"https?://[^\s]+", mail.outbox[-1].body).group(0)
    return parse_qs(urlsplit(link).query)["token"][0]


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
                   PUBLIC_BASE_URL="https://studycrew.example")
class AccountReadinessServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="student@example.com", password=VALID_PASSWORD)
        cls.other = User.objects.create_user(email="other@example.com", password=VALID_PASSWORD)

    def reset_link(self):
        request_password_reset(email=self.user.email, ip_address="127.0.0.1")
        return latest_token()

    def add_recovery(self):
        request_recovery_email(user=self.user, email="personal@example.com")
        confirm_recovery_email(token=latest_token())

    def test_unknown_and_disabled_reset_requests_send_nothing(self):
        request_password_reset(email="missing@example.com", ip_address="127.0.0.1")
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        request_password_reset(email=self.user.email, ip_address="127.0.0.1")
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_token_is_hashed_short_lived_and_uses_configured_origin(self):
        token = self.reset_link()
        row = AccountSecurityToken.objects.get()
        self.assertNotEqual(row.token_digest, token)
        self.assertEqual(len(row.token_digest), 64)
        self.assertGreaterEqual(len(token), 40)
        self.assertLessEqual(row.expires_at - timezone.now(), timedelta(minutes=15))
        self.assertIn("https://studycrew.example/account/password/reset/confirm/", mail.outbox[0].body)

    def test_password_reset_validates_password_and_does_not_consume_on_validation_failure(self):
        token = self.reset_link()
        with self.assertRaises(ValidationError):
            reset_password(token=token, new_password="123")
        self.assertIsNone(AccountSecurityToken.objects.get().consumed_at)
        reset_password(token=token, new_password=NEW_VALID_PASSWORD)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(NEW_VALID_PASSWORD))
        with self.assertRaises(ValidationError):
            reset_password(token=token, new_password=VALID_PASSWORD)

    def test_expired_and_forged_reset_tokens_are_rejected(self):
        token = self.reset_link()
        AccountSecurityToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        for candidate in (token, "not-a-token", "x" * 43):
            with self.assertRaises(ValidationError):
                reset_password(token=candidate, new_password=NEW_VALID_PASSWORD)

    def test_new_reset_request_invalidates_the_previous_link(self):
        first = self.reset_link()
        second = self.reset_link()
        with self.assertRaises(ValidationError):
            reset_password(token=first, new_password=NEW_VALID_PASSWORD)
        reset_password(token=second, new_password=NEW_VALID_PASSWORD)

    def test_reset_send_limit_counts_every_request_and_rotates_only_allowed_requests(self):
        for _ in range(8):
            request_password_reset(email=self.user.email, ip_address="127.0.0.1")
        self.assertEqual(len(mail.outbox), 5)
        self.assertEqual(AccountSecurityToken.objects.filter(consumed_at__isnull=True).count(), 1)

    def test_delivery_failure_does_not_expose_account_state_or_leave_an_usable_link(self):
        with patch("accounts.readiness_services.send_mail", side_effect=OSError("smtp unavailable")):
            request_password_reset(email=self.user.email, ip_address="127.0.0.1")
        self.assertFalse(AccountSecurityToken.objects.filter(consumed_at__isnull=True).exists())

    def test_mail_failure_logs_no_exception_text_recovery_link_or_recipient(self):
        secret = "https://studycrew.example/account/password/reset/confirm/?token=private-token"
        with patch("accounts.readiness_services.send_mail", side_effect=OSError(f"{self.user.email} {secret}")):
            with self.assertLogs("accounts.readiness_services", level="ERROR") as logs:
                request_password_reset(email=self.user.email, ip_address="127.0.0.1")
        logged = " ".join(logs.output)
        self.assertIn(str(self.user.pk), logged)
        self.assertNotIn(self.user.email, logged)
        self.assertNotIn("private-token", logged)
        self.assertNotIn("Traceback", logged)

    def test_password_change_or_signin_email_change_invalidates_old_links(self):
        token = self.reset_link()
        self.user.email = "changed@example.com"
        self.user.save(update_fields=["email"])
        with self.assertRaises(ValidationError):
            reset_password(token=token, new_password=NEW_VALID_PASSWORD)

    def test_password_reset_revokes_legacy_and_registered_sessions_without_affecting_other_users(self):
        self.client.force_login(self.user)
        mine = self.client.session.session_key
        from django.test import Client
        other_client = Client()
        other_client.force_login(self.other)
        theirs = other_client.session.session_key
        AccountDeviceSession.objects.create(user=self.user, session_key=mine, expires_at=timezone.now() + timedelta(hours=1))
        reset_password(token=self.reset_link(), new_password=NEW_VALID_PASSWORD)
        self.assertFalse(Session.objects.filter(pk=mine).exists())
        self.assertTrue(Session.objects.filter(pk=theirs).exists())
        self.assertFalse(AccountDeviceSession.objects.filter(user=self.user).exists())

    def test_reset_consumes_outstanding_login_otp(self):
        EmailOTPChallenge.objects.create(user=self.user, purpose="login", code_hash="x" * 64,
                                         expires_at=timezone.now() + timedelta(minutes=5), max_attempts=5,
                                         last_sent_at=timezone.now())
        reset_password(token=self.reset_link(), new_password=NEW_VALID_PASSWORD)
        self.assertFalse(EmailOTPChallenge.objects.filter(consumed_at__isnull=True).exists())

    def test_recovery_address_is_not_installed_until_link_confirmation(self):
        request_recovery_email(user=self.user, email="personal@example.com")
        self.assertFalse(RecoveryEmail.objects.exists())
        token = latest_token()
        confirm_recovery_email(token=token)
        self.assertEqual(RecoveryEmail.objects.get(user=self.user).email, "personal@example.com")
        with self.assertRaises(ValidationError):
            confirm_recovery_email(token=token)

    def test_recovery_address_must_differ_from_signin_address(self):
        with self.assertRaises(ValidationError):
            request_recovery_email(user=self.user, email=self.user.email)

    def test_recovery_request_requires_password_and_preverified_address(self):
        request_email_recovery(email=self.user.email, password=VALID_PASSWORD, ip_address="127.0.0.1")
        self.assertEqual(len(mail.outbox), 0)
        self.add_recovery()
        before = len(mail.outbox)
        request_email_recovery(email=self.user.email, password="wrong", ip_address="127.0.0.1")
        request_email_recovery(email="missing@example.com", password=VALID_PASSWORD, ip_address="127.0.0.1")
        self.assertEqual(len(mail.outbox), before)

    def test_email_recovery_verifies_both_mailboxes_and_does_not_change_password(self):
        self.add_recovery()
        request_email_recovery(email=self.user.email, password=VALID_PASSWORD, ip_address="127.0.0.1")
        self.assertEqual(mail.outbox[-1].to, ["personal@example.com"])
        first = latest_token()
        start_recovered_signin_email(token=first, new_email="new@example.com")
        second = latest_token()
        self.assertEqual(mail.outbox[-1].to, ["new@example.com"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "student@example.com")
        with self.assertRaises(ValidationError):
            start_recovered_signin_email(token=first, new_email="elsewhere@example.com")
        finish_recovered_signin_email(token=second)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")
        self.assertTrue(self.user.check_password(VALID_PASSWORD))
        self.assertIsNotNone(self.user.email_verified_at)
        with self.assertRaises(ValidationError):
            finish_recovered_signin_email(token=second)

    def test_removing_recovery_address_cancels_inprogress_recovery(self):
        self.add_recovery()
        request_email_recovery(email=self.user.email, password=VALID_PASSWORD, ip_address="127.0.0.1")
        start_recovered_signin_email(token=latest_token(), new_email="new@example.com")
        token = latest_token()
        remove_recovery_email(user=self.user)
        with self.assertRaises(ValidationError):
            finish_recovered_signin_email(token=token)

    def test_replacing_recovery_address_cancels_inprogress_recovery(self):
        self.add_recovery()
        request_email_recovery(email=self.user.email, password=VALID_PASSWORD, ip_address="127.0.0.1")
        start_recovered_signin_email(token=latest_token(), new_email="new@example.com")
        token = latest_token()
        request_recovery_email(user=self.user, email="another-personal@example.com")
        confirm_recovery_email(token=latest_token())
        with self.assertRaises(ValidationError):
            finish_recovered_signin_email(token=token)

    def test_recovery_cannot_claim_someone_elses_signin_address(self):
        self.add_recovery()
        request_email_recovery(email=self.user.email, password=VALID_PASSWORD, ip_address="127.0.0.1")
        with self.assertRaises(ValidationError):
            start_recovered_signin_email(token=latest_token(), new_email=self.other.email)

    def test_closure_requires_confirmation_and_owner_handover_for_active_project(self):
        project = Project.objects.create(name="Active team", created_by=self.user)
        ProjectMembership.objects.create(project=project, user=self.user, role="owner")
        for confirmation in ("wrong", "CLOSE MY ACCOUNT"):
            with self.assertRaises(ValidationError):
                close_account(user=self.user, confirmation=confirmation)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_archived_project_owner_can_close_and_history_is_preserved(self):
        project = Project.objects.create(name="Archived team", created_by=self.user, archived_at=timezone.now())
        membership = ProjectMembership.objects.create(project=project, user=self.user, role="owner")
        close_account(user=self.user, confirmation="CLOSE MY ACCOUNT")
        membership.refresh_from_db()
        self.user.refresh_from_db()
        project.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertIsNotNone(membership.removed_at)
        self.assertIsNotNone(project.archived_at)
        self.assertEqual(project.created_by_id, self.user.pk)
        self.assertTrue(ActivityEvent.objects.filter(project=project, actor=self.user, event_type="member_removed").exists())

    def test_closure_removes_identity_and_access_but_preserves_authored_work_and_evidence(self):
        project = Project.objects.create(name="Team project", created_by=self.other)
        ProjectMembership.objects.create(project=project, user=self.other, role="owner")
        membership = ProjectMembership.objects.create(project=project, user=self.user, role="member")
        task = Task.objects.create(project=project, title="Shared task", created_by=self.user)
        TaskAssignment.objects.create(task=task, user=self.user, assigned_by=self.other)
        comment = TaskComment.objects.create(task=task, author=self.user, body="My contribution")
        self.add_recovery()
        close_account(user=self.user, confirmation="CLOSE MY ACCOUNT")
        self.user.refresh_from_db()
        membership.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertIsNotNone(self.user.closed_at)
        self.assertFalse(self.user.has_usable_password())
        self.assertTrue(self.user.email.endswith("@closed.invalid"))
        self.assertIsNotNone(membership.removed_at)
        self.assertEqual(self.user.profile.display_name, "Closed account")
        self.assertFalse(RecoveryEmail.objects.filter(user=self.user).exists())
        self.assertFalse(TaskAssignment.objects.filter(user=self.user).exists())
        self.assertTrue(TaskComment.objects.filter(pk=comment.pk).exists())
        self.assertEqual(ActivityEvent.objects.filter(actor=self.user).count(), 2)

    def test_personal_download_excludes_other_account_details_and_security_secrets(self):
        self.reset_link()
        payload = json.loads(personal_data_download(self.user))
        self.assertEqual(payload["account"]["email"], self.user.email)
        text = json.dumps(payload)
        self.assertNotIn(self.other.email, text)
        self.assertNotIn("token_digest", text)
        self.assertNotIn("password", payload["account"])
        self.assertNotIn(self.user.password, text)

    def test_personal_download_is_rate_limited(self):
        for _ in range(3):
            personal_data_download(self.user)
        with self.assertRaises(ValidationError):
            personal_data_download(self.user)

    def test_download_includes_only_my_votes_claims_and_availability(self):
        from coordination.models import ContributionClaim, PollOption, PollVote, SchedulingPoll, WeeklyAvailability
        project = Project.objects.create(name="Privacy team", created_by=self.user)
        poll = SchedulingPoll.objects.create(project=project, creator=self.user, title="Meeting poll", participants=[])
        option = PollOption.objects.create(poll=poll, starts_at=timezone.now(), ends_at=timezone.now() + timedelta(hours=1))
        mine = PollVote.objects.create(option=option, user=self.user, response="yes")
        other = PollVote.objects.create(option=option, user=self.other, response="no")
        WeeklyAvailability.objects.create(project=project, user=self.user, time_zone="UTC", slots=[])
        WeeklyAvailability.objects.create(project=project, user=self.other, time_zone="UTC", slots=[])
        ContributionClaim.objects.create(project=project, author=self.user, title="My claim", statement="My personal record")
        ContributionClaim.objects.create(project=project, author=self.other, title="Other claim", statement="Other private statement")
        records = json.loads(personal_data_download(self.user))["records"]
        self.assertEqual([row["id"] for row in records["coordination.PollVote"]], [str(mine.pk)])
        self.assertNotIn(str(other.pk), json.dumps(records["coordination.PollVote"]))
        self.assertEqual(len(records["coordination.WeeklyAvailability"]), 1)
        self.assertEqual([row["statement"] for row in records["coordination.ContributionClaim"]], ["My personal record"])

    def test_download_withholds_other_invite_recipients_contact_details(self):
        project = Project.objects.create(name="Invite team", created_by=self.user)
        ProjectInvitation.objects.create(project=project, invited_by=self.user, invited_email="another-person@example.com",
                                         token_hash="a" * 64, expires_at=timezone.now() + timedelta(days=1))
        payload = json.loads(personal_data_download(self.user))
        self.assertNotIn("another-person@example.com", json.dumps(payload))
        self.assertEqual(len(payload["records"]["projects.ProjectInvitation"]), 1)
