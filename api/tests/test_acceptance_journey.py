"""One vertical acceptance journey across StudyCrew's public API contract."""

from datetime import timedelta
from tempfile import TemporaryDirectory

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from api.tests.base import APIDomainTestCase


class EndToEndAcceptanceJourneyTests(APIDomainTestCase):
    def test_project_collaboration_evidence_and_archive_journey(self):
        owner_client = self.authenticate(self.owner, client=APIClient())
        invitee_client = self.authenticate(self.outsider, client=APIClient())

        project_response = owner_client.post(
            "/api/v1/projects/",
            {
                "name": "Acceptance delivery",
                "description": "A complete assessed workflow",
                "due_at": None,
            },
            format="json",
        )
        self.assertEqual(project_response.status_code, 201, project_response.content)
        project_id = project_response.json()["id"]

        invitation_response = owner_client.post(
            "/api/v1/invitations/",
            {"project": project_id, "invited_email": self.outsider.email},
            format="json",
        )
        self.assertEqual(invitation_response.status_code, 201, invitation_response.content)
        invitation_id = invitation_response.json()["id"]
        inbox = invitee_client.get("/api/v1/invitations/")
        self.assertIn(invitation_id, {item["id"] for item in inbox.json()["results"]})
        accepted = invitee_client.post(
            f"/api/v1/invitations/{invitation_id}/accept/", {}, format="json"
        )
        self.assertEqual(accepted.status_code, 200, accepted.content)
        roster = owner_client.get("/api/v1/memberships/", {"project": project_id})
        self.assertEqual(roster.json()["count"], 2)

        task_response = owner_client.post(
            "/api/v1/tasks/",
            {
                "project": project_id,
                "title": "Complete linked acceptance flow",
                "description": "Invite, assign, discuss, meet and export",
                "priority": "high",
            },
            format="json",
        )
        self.assertEqual(task_response.status_code, 201, task_response.content)
        task_id = task_response.json()["id"]
        assigned = owner_client.put(
            f"/api/v1/tasks/{task_id}/assignees/",
            {"assignee_ids": [str(self.outsider.id)]},
            format="json",
        )
        self.assertEqual(assigned.status_code, 200, assigned.content)
        self.assertEqual(assigned.json()["assignees"][0]["id"], str(self.outsider.id))

        blocked = invitee_client.post(
            f"/api/v1/tasks/{task_id}/transition/",
            {"status": "blocked", "blocker_note": "Waiting for owner review"},
            format="json",
        )
        self.assertEqual(blocked.status_code, 200, blocked.content)
        comment = invitee_client.post(
            "/api/v1/comments/",
            {
                "task": task_id,
                "body": "Please review the blocker.",
                "mentioned_user_ids": [str(self.owner.id)],
            },
            format="json",
        )
        self.assertEqual(comment.status_code, 201, comment.content)
        owner_notifications = owner_client.get("/api/v1/notifications/")
        self.assertIn(
            "comment_mention",
            {item["notification_type"] for item in owner_notifications.json()["results"]},
        )

        starts_at = timezone.now() + timedelta(days=1)
        meeting = owner_client.post(
            "/api/v1/meetings/",
            {
                "project": project_id,
                "title": "Acceptance review",
                "starts_at": starts_at.isoformat(),
                "ends_at": (starts_at + timedelta(hours=1)).isoformat(),
                "location": "Online",
                "agenda": "Resolve the blocker",
            },
            format="json",
        )
        self.assertEqual(meeting.status_code, 201, meeting.content)
        meeting_id = meeting.json()["id"]
        rsvp = invitee_client.put(
            f"/api/v1/meetings/{meeting_id}/rsvp/",
            {"response": "accepted", "availability_note": "Available"},
            format="json",
        )
        self.assertEqual(rsvp.status_code, 200, rsvp.content)
        refreshed_meetings = owner_client.get(
            "/api/v1/meetings/", {"project": project_id}
        )
        self.assertEqual(
            refreshed_meetings.json()["results"][0]["attendance_counts"]["accepted"],
            1,
        )

        self.assertEqual(owner_client.delete(f"/api/v1/tasks/{task_id}/").status_code, 204)
        archived_tasks = owner_client.get(
            "/api/v1/tasks/", {"project": project_id, "scope": "archived"}
        )
        self.assertIn(task_id, {item["id"] for item in archived_tasks.json()["results"]})
        self.assertEqual(owner_client.delete(f"/api/v1/projects/{project_id}/").status_code, 204)
        archived_projects = owner_client.get("/api/v1/projects/", {"scope": "archived"})
        self.assertIn(project_id, {item["id"] for item in archived_projects.json()["results"]})
        self.assertEqual(
            owner_client.patch(
                f"/api/v1/tasks/{task_id}/", {"title": "Forbidden rewrite"}, format="json"
            ).status_code,
            400,
        )

        today = timezone.localdate().isoformat()
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            export = owner_client.post(
                "/api/v1/exports/",
                {
                    "project": project_id,
                    "format": "csv",
                    "range_start": today,
                    "range_end": today,
                },
                format="json",
            )
            self.assertEqual(export.status_code, 201, export.content)
            self.assertEqual(export.json()["status"], "ready")
            download = owner_client.get(
                f"/api/v1/exports/{export.json()['id']}/download/"
            )
            exported_text = b"".join(download.streaming_content).decode("utf-8-sig")
            download.close()
            self.assertIn("Acceptance delivery", exported_text)
            self.assertIn("API Outsider", exported_text)
