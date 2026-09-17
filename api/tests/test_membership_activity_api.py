from datetime import datetime, timedelta, timezone as datetime_timezone
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from activity.models import ActivityEvent, Notification
from activity.services import create_notification, record_event
from api.tests.base import APIDomainTestCase
from projects.models import ProjectMembership
from projects.services import invite_member


class MembershipActivityAPITests(APIDomainTestCase):
    def test_invitation_list_accept_and_membership_creation(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.outsider.email,
        )
        self.authenticate(self.outsider)
        listed = self.client.get("/api/v1/invitations/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["count"], 1)
        accepted = self.client.post(
            f"/api/v1/invitations/{dispatch.invitation.id}/accept/", {}, format="json"
        )
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.assertTrue(
            ProjectMembership.objects.active().filter(
                project=self.project, user=self.outsider
            ).exists()
        )
        replay = self.client.post(
            f"/api/v1/invitations/{dispatch.invitation.id}/accept/", {}, format="json"
        )
        self.assertEqual(replay.status_code, 400)

    def test_owner_can_change_member_role_and_member_cannot(self):
        membership = ProjectMembership.objects.get(project=self.project, user=self.member)
        self.authenticate(self.member)
        denied = self.client.patch(
            f"/api/v1/memberships/{membership.id}/", {"role": "facilitator"}, format="json"
        )
        self.assertEqual(denied.status_code, 403)
        self.authenticate(self.owner)
        allowed = self.client.patch(
            f"/api/v1/memberships/{membership.id}/", {"role": "facilitator"}, format="json"
        )
        self.assertEqual(allowed.status_code, 200, allowed.content)
        rejected_owner = self.client.patch(
            f"/api/v1/memberships/{membership.id}/", {"role": "owner"}, format="json"
        )
        self.assertEqual(rejected_owner.status_code, 400)
        self.assertIn("role", rejected_owner.json()["error"]["fields"])

    def test_notification_owner_can_mark_read_but_other_user_cannot(self):
        event = record_event(
            project=self.project,
            actor=self.owner,
            event_type=ActivityEvent.Type.TASK_ASSIGNEES_CHANGED,
            target_type=ActivityEvent.TargetType.TASK,
            target_id=self.project.id,
        )
        notification = create_notification(
            event=event,
            recipient=self.member,
            notification_type=Notification.Type.TASK_ASSIGNMENT,
            target_url=f"/app/projects/{self.project.id}/",
        )
        self.authenticate(self.owner)
        self.assertEqual(
            self.client.patch(f"/api/v1/notifications/{notification.id}/read/").status_code,
            403,
        )
        self.authenticate(self.member)
        response = self.client.patch(f"/api/v1/notifications/{notification.id}/read/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_read"])

    def test_insights_include_zero_member_and_event(self):
        record_event(
            project=self.project,
            actor=self.owner,
            event_type=ActivityEvent.Type.COMMENT_CREATED,
            target_type=ActivityEvent.TargetType.COMMENT,
            target_id=self.project.id,
        )
        self.authenticate(self.member)
        today = timezone.localdate(
            timezone.now(), ZoneInfo(self.member.profile.time_zone)
        ).isoformat()
        response = self.client.get(
            f"/api/v1/projects/{self.project.id}/insights/?range_start={today}&range_end={today}"
        )
        self.assertEqual(response.status_code, 200, response.content)
        by_name = {row["display_name"]: row for row in response.json()["members"]}
        self.assertEqual(by_name["API Owner"]["total_events"], 1)
        self.assertEqual(by_name["API Member"]["total_events"], 0)

    def test_insight_default_range_uses_the_requesting_users_calendar_date(self):
        self.member.profile.time_zone = "Pacific/Kiritimati"
        self.member.profile.save(update_fields=("time_zone", "updated_at"))
        instant = datetime(2026, 1, 1, 11, 30, tzinfo=datetime_timezone.utc)
        captured = {}

        def fake_insights(**kwargs):
            captured.update(kwargs)
            return {
                "range_start": kwargs["range_start"],
                "range_end": kwargs["range_end"],
                "event_type": "",
                "members": [],
                "events": ActivityEvent.objects.none(),
            }

        with patch("api.views.timezone.now", return_value=instant), patch(
            "api.views.contribution_insights",
            side_effect=fake_insights,
        ):
            self.authenticate(self.member)
            response = self.client.get(f"/api/v1/projects/{self.project.id}/insights/")

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(captured["range_end"].isoformat(), "2026-01-02")
        self.assertEqual(captured["range_start"].isoformat(), "2025-12-03")

    def test_insights_truncation_flag_uses_a_real_sentinel_event(self):
        today = timezone.localdate()
        self.authenticate(self.member)

        def event_rows(count):
            return [
                ActivityEvent(
                    id=uuid4(),
                    project=self.project,
                    actor=self.owner,
                    event_type=ActivityEvent.Type.PROJECT_UPDATED,
                    target_type=ActivityEvent.TargetType.PROJECT,
                    target_id=self.project.id,
                    metadata={},
                    occurred_at=timezone.now(),
                )
                for _ in range(count)
            ]

        for count, expected in ((200, False), (201, True)):
            result = {
                "range_start": today,
                "range_end": today,
                "event_type": "",
                "members": [],
                "events": event_rows(count),
            }
            with self.subTest(count=count), patch(
                "api.views.contribution_insights", return_value=result
            ):
                response = self.client.get(
                    f"/api/v1/projects/{self.project.id}/insights/"
                    f"?range_start={today.isoformat()}&range_end={today.isoformat()}"
                )
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["events_truncated"], expected)
                self.assertEqual(len(response.json()["events"]), min(count, 200))

    def test_csv_export_create_list_and_download(self):
        self.authenticate(self.owner)
        today = timezone.localdate().isoformat()
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            created = self.client.post(
                "/api/v1/exports/",
                {
                    "project": str(self.project.id),
                    "format": "csv",
                    "range_start": today,
                    "range_end": today,
                },
                format="json",
            )
            self.assertEqual(created.status_code, 201, created.content)
            self.assertEqual(created.json()["status"], "ready")
            export_id = created.json()["id"]
            listed = self.client.get("/api/v1/exports/")
            self.assertEqual(listed.json()["count"], 1)
            download = self.client.get(f"/api/v1/exports/{export_id}/download/")
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download["Content-Type"], "text/csv")
            list(download.streaming_content)
            download.close()
            with override_settings(USE_X_ACCEL_REDIRECT=True):
                proxied = self.client.get(f"/api/v1/exports/{export_id}/download/")
            self.assertEqual(proxied.status_code, 200)
            self.assertEqual(proxied["Content-Type"], "text/csv")
            self.assertTrue(proxied["X-Accel-Redirect"].startswith("/protected-media/exports/"))
