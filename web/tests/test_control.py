from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from activity.models import SiteAuditEvent
from projects.models import Project, ProjectMembership
from tasks.models import ContentReport, Task, TaskComment
from web.services import is_site_moderator, require_site_moderator, set_user_active
from web.views import _audit_payload


class ControlCentreTests(TestCase):
    password = "Strong!Passphrase42"

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.moderator = User.objects.create_user(
            email="moderator@example.com",
            password=cls.password,
            display_name="Site Moderator",
            is_staff=True,
        )
        cls.moderator.user_permissions.add(
            Permission.objects.get(codename="manage_user_status"),
            Permission.objects.get(codename="moderate_reports"),
        )
        cls.member = User.objects.create_user(
            email="control-member@example.com", password=cls.password, display_name="Member"
        )
        cls.project = Project.objects.create(name="Moderated project", created_by=cls.member)
        ProjectMembership.objects.create(
            project=cls.project, user=cls.member, role=ProjectMembership.Role.OWNER
        )
        task = Task.objects.create(
            project=cls.project, created_by=cls.member, title="Reported task"
        )
        cls.comment = TaskComment.objects.create(task=task, author=cls.member, body="Reported text")
        cls.report = ContentReport.objects.create(
            comment=cls.comment,
            reporter=cls.member,
            reason=ContentReport.Reason.SPAM,
        )

    def test_control_panel_denies_visitors_and_regular_users(self):
        self.assertEqual(self.client.get("/control/").status_code, 302)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get("/control/").status_code, 403)

    def test_moderator_sees_limited_panel_without_sensitive_fields(self):
        self.client.force_login(self.moderator)
        response = self.client.get("/control/")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Pending reports", body)
        self.assertIn(self.member.email, body)
        self.assertNotIn(self.member.password, body)
        self.assertNotIn("DJANGO_SECRET_KEY", body)

    def test_control_panel_searches_by_trimmed_name_or_email(self):
        self.client.force_login(self.moderator)
        response = self.client.get("/control/", {"q": "  control-member@  "})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.member.email)
        self.assertEqual(response.context["query"], "control-member@")

    def test_moderator_can_suspend_and_restore_user_via_json(self):
        self.client.force_login(self.moderator)
        endpoint = f"/control/users/{self.member.id}/status/"
        suspended = self.client.post(
            endpoint,
            {"active": "false"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(suspended.status_code, 200)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertEqual(suspended.json()["audit_event"]["action"], "User disabled")
        restored = self.client.post(
            endpoint,
            {"active": "true"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(restored.status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
        self.assertEqual(restored.json()["audit_event"]["action"], "User enabled")
        self.assertEqual(SiteAuditEvent.objects.filter(target_id=self.member.id).count(), 2)

    def test_moderator_cannot_suspend_self(self):
        self.client.force_login(self.moderator)
        response = self.client.post(
            f"/control/users/{self.moderator.id}/status/",
            {"active": "false"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.moderator.refresh_from_db()
        self.assertTrue(self.moderator.is_active)

    def test_invalid_user_state_returns_validation_response(self):
        self.client.force_login(self.moderator)
        endpoint = f"/control/users/{self.member.id}/status/"

        json_response = self.client.post(
            endpoint,
            {"active": "perhaps"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(json_response.status_code, 400)
        self.assertEqual(json_response.json()["error"]["code"], "validation_error")

        html_response = self.client.post(endpoint, {"active": "perhaps"})
        self.assertRedirects(html_response, "/control/", fetch_redirect_response=False)

    def test_html_user_action_redirects_to_control_dashboard(self):
        self.client.force_login(self.moderator)
        response = self.client.post(
            f"/control/users/{self.member.id}/status/",
            {"active": "false"},
        )
        self.assertRedirects(response, "/control/", fetch_redirect_response=False)

    def test_report_resolution_can_soft_remove_comment(self):
        self.client.force_login(self.moderator)
        response = self.client.post(
            f"/control/reports/{self.report.id}/resolve/",
            {
                "outcome": "resolved",
                "resolution_note": "Confirmed spam",
                "remove_comment": "true",
            },
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["pending_reports"], 0)
        self.assertEqual(response.json()["audit_event"]["action"], "Content report resolved")
        self.report.refresh_from_db()
        self.comment.refresh_from_db()
        self.assertEqual(self.report.status, ContentReport.Status.RESOLVED)
        self.assertIsNotNone(self.comment.deleted_at)

    def test_invalid_report_resolution_returns_json_validation_error(self):
        self.client.force_login(self.moderator)
        response = self.client.post(
            f"/control/reports/{self.report.id}/resolve/",
            {"outcome": "unknown", "resolution_note": "No valid outcome"},
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")

    def test_html_report_resolution_redirects(self):
        self.client.force_login(self.moderator)
        response = self.client.post(
            f"/control/reports/{self.report.id}/resolve/",
            {"outcome": "dismissed", "resolution_note": "Not a violation"},
        )
        self.assertRedirects(response, "/control/", fetch_redirect_response=False)

    def test_public_home_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "StudyCrew")
        self.assertContains(response, "without the guesswork")
        self.assertContains(response, "Meet with context")
        self.assertContains(response, "No contribution scores")
        self.assertContains(response, 'data-reveal="rise"')
        self.assertContains(response, 'role="tablist"')
        self.assertContains(response, 'data-feature-tab="meetings"')
        self.assertContains(response, 'data-feature-view="activity"')
        self.assertContains(response, "Pause automatic feature preview")
        self.assertContains(response, "/static/css/app.css?v=")
        self.assertContains(response, "/static/js/site.js?v=")

    def test_audit_payload_falls_back_to_email_for_legacy_user_without_profile(self):
        raw_user = get_user_model().objects.create(
            email="legacy-moderator@example.com",
            is_active=True,
            is_staff=True,
        )
        event = SiteAuditEvent.objects.create(
            actor=raw_user,
            action=SiteAuditEvent.Action.USER_DISABLED,
            target_type="user",
            target_id=self.member.id,
        )

        self.assertEqual(_audit_payload(event)["actor"], raw_user.email)


class ControlServiceTests(TestCase):
    password = "Strong!Passphrase42"

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.moderator = User.objects.create_user(
            email="service-moderator@example.com",
            password=cls.password,
            display_name="Service Moderator",
            is_staff=True,
        )
        cls.moderator.user_permissions.add(
            Permission.objects.get(codename="manage_user_status"),
            Permission.objects.get(codename="moderate_reports"),
        )
        cls.target = User.objects.create_user(
            email="service-target@example.com",
            password=cls.password,
            display_name="Service Target",
        )

    def test_site_moderator_requires_all_account_flags_and_permissions(self):
        self.assertFalse(is_site_moderator(AnonymousUser()))
        self.assertFalse(is_site_moderator(self.target))
        self.assertTrue(is_site_moderator(self.moderator))
        require_site_moderator(self.moderator)
        with self.assertRaises(PermissionDenied):
            require_site_moderator(self.target)

        self.moderator.is_active = False
        self.assertFalse(is_site_moderator(self.moderator))

    def test_suspend_invalidates_only_target_sessions_and_records_count(self):
        from django.test import Client

        target_client = Client()
        moderator_client = Client()
        target_client.force_login(self.target)
        moderator_client.force_login(self.moderator)
        target_session = target_client.session.session_key
        moderator_session = moderator_client.session.session_key

        changed = set_user_active(actor=self.moderator, target=self.target, active=False)
        self.assertFalse(changed.is_active)
        self.assertFalse(Session.objects.filter(session_key=target_session).exists())
        self.assertTrue(Session.objects.filter(session_key=moderator_session).exists())
        event = SiteAuditEvent.objects.get(target_id=self.target.id)
        self.assertEqual(event.metadata["sessions_invalidated"], 1)

    def test_noop_status_change_has_no_audit_event(self):
        unchanged = set_user_active(actor=self.moderator, target=self.target, active=True)
        self.assertTrue(unchanged.is_active)
        self.assertFalse(SiteAuditEvent.objects.filter(target_id=self.target.id).exists())

    def test_actor_cannot_manage_self_or_superuser(self):
        with self.assertRaises(ValidationError):
            set_user_active(actor=self.moderator, target=self.moderator, active=False)

        superuser = get_user_model().objects.create_superuser(
            email="protected@example.com",
            password=self.password,
            display_name="Protected User",
        )
        with self.assertRaises(PermissionDenied):
            set_user_active(actor=self.moderator, target=superuser, active=False)


class CreateModeratorCommandTests(TestCase):
    @patch("accounts.management.commands.create_site_moderator.getpass")
    def test_command_rejects_invalid_email_before_requesting_password(self, getpass):
        with self.assertRaises(CommandError):
            call_command(
                "create_site_moderator",
                email="not-an-email",
                display_name="Invalid Email Moderator",
            )

        getpass.assert_not_called()
        self.assertFalse(get_user_model().objects.filter(email="not-an-email").exists())

    @patch("accounts.management.commands.create_site_moderator.getpass")
    def test_command_rejects_invalid_display_name_before_requesting_password(self, getpass):
        with self.assertRaises(CommandError):
            call_command(
                "create_site_moderator",
                email="bad-name@example.com",
                display_name="X",
            )

        getpass.assert_not_called()
        self.assertFalse(get_user_model().objects.filter(email="bad-name@example.com").exists())

    @patch(
        "accounts.management.commands.create_site_moderator.getpass",
        side_effect=["Strong!ModeratorPass42", "Strong!ModeratorPass42"],
    )
    def test_command_creates_least_privilege_moderator(self, _getpass):
        output = StringIO()
        call_command(
            "create_site_moderator",
            email="new-moderator@example.com",
            display_name="New Moderator",
            stdout=output,
        )
        user = get_user_model().objects.get(email="new-moderator@example.com")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.has_perm("accounts.manage_user_status"))
        self.assertTrue(user.has_perm("tasks.moderate_reports"))
        self.assertIn("Created site moderator", output.getvalue())

    @patch(
        "accounts.management.commands.create_site_moderator.getpass",
        side_effect=["password1", "password1"],
    )
    def test_command_rejects_simple_password(self, _getpass):
        with self.assertRaises(CommandError):
            call_command(
                "create_site_moderator",
                email="weak@example.com",
                display_name="Weak Moderator",
            )
        self.assertFalse(get_user_model().objects.filter(email="weak@example.com").exists())
