from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from api.tests.base import APIDomainTestCase
from integrations.nager_date import PublicHolidayResult
from meetings.models import Meeting
from tasks.models import Task, TaskComment


class CommentMeetingAPITests(APIDomainTestCase):
    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(
            project=self.project, created_by=self.owner, title="Discuss implementation"
        )

    def test_comment_full_crud_and_xss_payload_remains_text(self):
        self.authenticate(self.member)
        xss = '<script>window.__owned = true</script>'
        created = self.client.post(
            "/api/v1/comments/",
            {"task": str(self.task.id), "body": xss},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        comment_id = created.json()["id"]
        self.assertEqual(created.json()["body"], xss)
        listed = self.client.get(f"/api/v1/comments/?task={self.task.id}")
        self.assertEqual(listed.json()["results"][0]["body"], xss)
        updated = self.client.put(
            f"/api/v1/comments/{comment_id}/", {"body": "Safe edited text"}, format="json"
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.client.delete(f"/api/v1/comments/{comment_id}/").status_code, 204)
        comment = TaskComment.objects.get(id=comment_id)
        self.assertIsNotNone(comment.deleted_at)
        self.assertEqual(self.client.get(f"/api/v1/comments/{comment_id}/").json()["body"], "")

    def test_non_author_non_moderator_cannot_change_comment(self):
        comment = TaskComment.objects.create(task=self.task, author=self.owner, body="Owner text")
        self.authenticate(self.member)
        response = self.client.patch(
            f"/api/v1/comments/{comment.id}/", {"body": "Changed"}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_partial_comment_update_requires_body_instead_of_server_error(self):
        comment = TaskComment.objects.create(task=self.task, author=self.member, body="Original")
        self.authenticate(self.member)
        response = self.client.patch(
            f"/api/v1/comments/{comment.id}/", {}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        self.assertIn("body", response.json()["error"]["fields"])

    def test_comment_update_rejects_create_only_fields(self):
        comment = TaskComment.objects.create(task=self.task, author=self.member, body="Original")
        other_task = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Other discussion",
        )
        self.authenticate(self.member)

        response = self.client.patch(
            f"/api/v1/comments/{comment.id}/",
            {
                "body": "Attempted move",
                "task": str(other_task.id),
                "mentioned_user_ids": [str(self.owner.id)],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            set(response.json()["error"]["fields"]),
            {"task", "mentioned_user_ids"},
        )
        comment.refresh_from_db()
        self.assertEqual(comment.body, "Original")
        self.assertEqual(comment.task_id, self.task.id)

    def test_comment_report_endpoint(self):
        comment = TaskComment.objects.create(task=self.task, author=self.owner, body="Report text")
        self.authenticate(self.member)
        response = self.client.post(
            f"/api/v1/comments/{comment.id}/report/",
            {"reason": "spam", "details": "Repeated links"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["status"], "pending")

    def test_meeting_full_crud_rsvp_and_cancel(self):
        self.authenticate(self.owner)
        starts = timezone.now() + timedelta(days=2)
        created = self.client.post(
            "/api/v1/meetings/",
            {
                "project": str(self.project.id),
                "title": "Sprint planning",
                "starts_at": starts.isoformat(),
                "ends_at": (starts + timedelta(hours=1)).isoformat(),
                "location": "Library room 2",
                "agenda": "Review the task board",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        meeting_id = created.json()["id"]
        listed = self.client.get(f"/api/v1/meetings/?project={self.project.id}")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["count"], 1)
        changed = self.client.patch(
            f"/api/v1/meetings/{meeting_id}/",
            {"title": "Updated sprint planning"},
            format="json",
        )
        self.assertEqual(changed.status_code, 200, changed.content)
        self.authenticate(self.member)
        rsvp = self.client.put(
            f"/api/v1/meetings/{meeting_id}/rsvp/",
            {"response": "accepted", "availability_note": "On time"},
            format="json",
        )
        self.assertEqual(rsvp.status_code, 200, rsvp.content)
        self.assertEqual(rsvp.json()["my_response"], "accepted")
        self.assertEqual(rsvp.json()["my_availability_note"], "On time")
        self.authenticate(self.owner)
        self.assertEqual(self.client.delete(f"/api/v1/meetings/{meeting_id}/").status_code, 204)
        self.assertIsNotNone(Meeting.objects.get(id=meeting_id).cancelled_at)

    def test_invalid_meeting_time_returns_field_error(self):
        self.authenticate(self.owner)
        starts = timezone.now() + timedelta(days=1)
        response = self.client.post(
            "/api/v1/meetings/",
            {
                "project": str(self.project.id),
                "title": "Invalid meeting",
                "starts_at": starts.isoformat(),
                "ends_at": starts.isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("ends_at", response.json()["error"]["fields"])

    def test_meeting_put_requires_a_complete_replace_payload(self):
        meeting = Meeting.objects.create(
            project=self.project,
            organiser=self.owner,
            title="Complete meeting replacement",
            starts_at=timezone.now() + timedelta(days=2),
            ends_at=timezone.now() + timedelta(days=2, hours=1),
        )
        self.authenticate(self.owner)

        response = self.client.put(f"/api/v1/meetings/{meeting.id}/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            set(response.json()["error"]["fields"]),
            {"title", "starts_at", "ends_at", "location", "agenda"},
        )

    @patch("meetings.selectors.get_australian_public_holidays", create=True)
    def test_holiday_advisory_failure_does_not_affect_meeting(self, _unused):
        meeting = Meeting.objects.create(
            project=self.project,
            organiser=self.owner,
            title="Resilient meeting",
            starts_at=timezone.now() + timedelta(days=3),
            ends_at=timezone.now() + timedelta(days=3, hours=1),
        )
        self.authenticate(self.owner)
        with patch(
            "integrations.nager_date.get_australian_public_holidays",
            return_value=PublicHolidayResult((), "unavailable", False),
        ):
            response = self.client.get(f"/api/v1/meetings/{meeting.id}/holiday/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["available"])
        self.assertTrue(Meeting.objects.filter(id=meeting.id).exists())
