from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone

from activity.models import ActivityEvent, Notification
from activity.services import create_notification, record_event
from api.tests.base import APIDomainTestCase
from projects.models import ProjectInvitation, ProjectMembership
from projects.services import invite_member
from tasks.models import Task


class AdditionalAPIViewBranchTests(APIDomainTestCase):
    def test_me_requires_the_complete_site_moderator_permission_set(self):
        User = get_user_model()
        partial_moderator = User.objects.create_user(
            email="partial-moderator@example.com",
            password=self.password,
            display_name="Partial Moderator",
            is_staff=True,
        )
        partial_moderator.user_permissions.add(
            Permission.objects.get(codename="moderate_reports")
        )
        self.authenticate(partial_moderator)
        response = self.client.get("/api/v1/me/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["permissions"]["site_moderator"])

    def test_profile_get_and_complete_update(self):
        self.authenticate(self.member)
        current = self.client.get("/api/v1/profile/")
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["email"], self.member.email)

        updated = self.client.put(
            "/api/v1/profile/",
            {
                "display_name": "Complete Profile",
                "course_code": "ICT3609",
                "time_zone": "Australia/Perth",
                "biography": "API profile update",
                "avatar_url": "https://example.com/avatar.png",
            },
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(updated.json()["course_code"], "ICT3609")

    def test_profile_put_requires_every_writable_field(self):
        self.authenticate(self.member)

        response = self.client.put(
            "/api/v1/profile/",
            {"display_name": "Incomplete Profile"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            set(response.json()["error"]["fields"]),
            {"course_code", "time_zone", "biography", "avatar_url"},
        )

    def test_project_list_and_activity_feed(self):
        event = record_event(
            project=self.project,
            actor=self.owner,
            event_type=ActivityEvent.Type.PROJECT_UPDATED,
            target_type=ActivityEvent.TargetType.PROJECT,
            target_id=self.project.id,
        )
        self.authenticate(self.member)
        listed = self.client.get("/api/v1/projects/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["count"], 1)

        activity = self.client.get(f"/api/v1/projects/{self.project.id}/activity/")
        self.assertEqual(activity.status_code, 200, activity.content)
        self.assertEqual(activity.json()["results"][0]["id"], str(event.id))

    def test_task_create_reports_each_required_service_field(self):
        self.authenticate(self.owner)
        without_project = self.client.post(
            "/api/v1/tasks/", {"title": "Valid task title"}, format="json"
        )
        self.assertEqual(without_project.status_code, 400)
        self.assertIn("project", without_project.json()["error"]["fields"])

        without_title = self.client.post(
            "/api/v1/tasks/", {"project": str(self.project.id)}, format="json"
        )
        self.assertEqual(without_title.status_code, 400)
        self.assertIn("title", without_title.json()["error"]["fields"])

    def test_comment_and_meeting_lists_require_parent_and_create_requires_fields(self):
        self.authenticate(self.owner)
        comment_list = self.client.get("/api/v1/comments/")
        self.assertEqual(comment_list.status_code, 400)
        self.assertIn("task", comment_list.json()["error"]["fields"])

        comment_create = self.client.post(
            "/api/v1/comments/", {"body": "Valid body"}, format="json"
        )
        self.assertEqual(comment_create.status_code, 400)
        self.assertIn("task", comment_create.json()["error"]["fields"])

        meeting_list = self.client.get("/api/v1/meetings/")
        self.assertEqual(meeting_list.status_code, 400)
        self.assertIn("project", meeting_list.json()["error"]["fields"])

        starts = timezone.now()
        meeting_create = self.client.post(
            "/api/v1/meetings/",
            {
                "project": str(self.project.id),
                "title": "Incomplete meeting",
                "starts_at": starts.isoformat(),
            },
            format="json",
        )
        self.assertEqual(meeting_create.status_code, 400)
        self.assertIn("ends_at", meeting_create.json()["error"]["fields"])

    def test_owner_invitation_create_project_list_and_cancel(self):
        self.authenticate(self.owner)
        created = self.client.post(
            "/api/v1/invitations/",
            {
                "project": str(self.project.id),
                "invited_email": "new-collaborator@example.com",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertTrue(created.json()["share_token"])
        invitation_id = created.json()["id"]

        listed = self.client.get(
            "/api/v1/invitations/", {"project": str(self.project.id)}
        )
        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertEqual(listed.json()["count"], 1)

        cancelled = self.client.delete(f"/api/v1/invitations/{invitation_id}/")
        self.assertEqual(cancelled.status_code, 204)
        self.assertEqual(
            ProjectInvitation.objects.get(id=invitation_id).status,
            ProjectInvitation.Status.CANCELLED,
        )

    def test_invitee_can_decline_from_in_app_inbox(self):
        dispatch = invite_member(
            actor=self.owner,
            project=self.project,
            invited_email=self.outsider.email,
        )
        self.authenticate(self.outsider)
        response = self.client.post(
            f"/api/v1/invitations/{dispatch.invitation.id}/decline/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], ProjectInvitation.Status.DECLINED)

    def test_membership_list_remove_and_transfer_ownership(self):
        User = get_user_model()
        removable = User.objects.create_user(
            email="removable@example.com",
            password=self.password,
            display_name="Removable Member",
        )
        removable_membership = ProjectMembership.objects.create(
            project=self.project, user=removable
        )
        incoming = User.objects.create_user(
            email="incoming-owner@example.com",
            password=self.password,
            display_name="Incoming Owner",
        )
        incoming_membership = ProjectMembership.objects.create(
            project=self.project, user=incoming
        )

        self.authenticate(self.owner)
        missing_parent = self.client.get("/api/v1/memberships/")
        self.assertEqual(missing_parent.status_code, 400)
        listed = self.client.get(
            "/api/v1/memberships/", {"project": str(self.project.id)}
        )
        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertEqual(listed.json()["count"], 4)

        removed = self.client.delete(
            f"/api/v1/memberships/{removable_membership.id}/"
        )
        self.assertEqual(removed.status_code, 204)
        removable_membership.refresh_from_db()
        self.assertIsNotNone(removable_membership.removed_at)

        transferred = self.client.post(
            f"/api/v1/memberships/{incoming_membership.id}/transfer-ownership/",
            {},
            format="json",
        )
        self.assertEqual(transferred.status_code, 200, transferred.content)
        self.assertEqual(transferred.json()["role"], ProjectMembership.Role.OWNER)
        self.assertEqual(
            ProjectMembership.objects.get(project=self.project, user=self.owner).role,
            ProjectMembership.Role.FACILITATOR,
        )

    def test_membership_update_without_role_returns_validation_error(self):
        membership = ProjectMembership.objects.get(project=self.project, user=self.member)
        self.authenticate(self.owner)
        for method in (self.client.put, self.client.patch):
            with self.subTest(method=method.__name__):
                response = method(
                    f"/api/v1/memberships/{membership.id}/",
                    {},
                    format="json",
                )
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("role", response.json()["error"]["fields"])

    def test_notification_list_supports_unread_filter(self):
        first_event = record_event(
            project=self.project,
            actor=self.owner,
            event_type=ActivityEvent.Type.TASK_ASSIGNED,
            target_type=ActivityEvent.TargetType.PROJECT,
            target_id=self.project.id,
        )
        unread = create_notification(
            event=first_event,
            recipient=self.member,
            notification_type=Notification.Type.TASK_ASSIGNMENT,
            target_url=f"/app/projects/{self.project.id}/",
        )
        second_event = record_event(
            project=self.project,
            actor=self.owner,
            event_type=ActivityEvent.Type.MEETING_UPDATED,
            target_type=ActivityEvent.TargetType.PROJECT,
            target_id=self.project.id,
        )
        create_notification(
            event=second_event,
            recipient=self.member,
            notification_type=Notification.Type.MEETING_CHANGE,
            target_url=f"/app/projects/{self.project.id}/meetings/",
        )
        unread.read_at = timezone.now()
        unread.save(update_fields=("read_at", "updated_at"))

        self.authenticate(self.member)
        response = self.client.get("/api/v1/notifications/?unread=true")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["count"], 1)

    def test_list_query_contracts_reject_malformed_values(self):
        self.authenticate(self.owner)
        cases = (
            ("/api/v1/tasks/?project=not-a-uuid", "project"),
            (f"/api/v1/tasks/?project={self.project.id}&q={'x' * 201}", "q"),
            ("/api/v1/comments/?task=not-a-uuid", "task"),
            ("/api/v1/meetings/?project=not-a-uuid", "project"),
            ("/api/v1/invitations/?project=not-a-uuid", "project"),
            ("/api/v1/memberships/?project=not-a-uuid", "project"),
            ("/api/v1/notifications/?unread=perhaps", "unread"),
        )

        for url, field in cases:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn(field, response.json()["error"]["fields"])
