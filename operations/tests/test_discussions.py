from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.session_security import MFA_VERIFIED_SESSION_KEY
from projects.models import Project, ProjectMembership
from tasks.models import Task, TaskAssignment
from operations.models import UserAlert, OutboundMessage, UserBlock, PostReply
from operations import discussion_services as service
from operations.services import schedule_blocked_tasks, message_eligible
from operations.worker import remove_stale_alerts


class DiscussionTests(TestCase):
    def test_reply_pagination_is_bounded_authorized_and_preserves_removed_tombstones(self):
        post = self.post()
        PostReply.objects.bulk_create([PostReply(post=post, author=self.member, body=f"Reply {index}") for index in range(28)])
        first = self.auth(self.owner).get(f"/api/v1/operations/projects/{self.project.pk}/posts/").data["results"][0]
        self.assertEqual(len(first["replies"]), 25); self.assertEqual(first["reply_pagination"]["total"], 28)
        url = f"/api/v1/operations/posts/{post.pk}/replies/?page=2"
        response = self.auth(self.member).get(url)
        self.assertEqual(len(response.data["results"]), 3)
        self.assertEqual(self.auth(self.outsider).get(url).status_code, 403)
        post.removed_at = timezone.now(); post.save()
        self.assertTrue(all(row["body"] == "" for row in self.auth(self.member).get(url).data["results"]))

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user(email="post-owner@example.com", password="Password!Valid42", display_name="Owner", email_verified_at=timezone.now())
        cls.member = User.objects.create_user(email="post-member@example.com", password="Password!Valid42", display_name="Member", email_verified_at=timezone.now())
        cls.outsider = User.objects.create_user(email="post-outsider@example.com", password="Password!Valid42", display_name="Outsider")
        cls.project = Project.objects.create(name="Discussion team", created_by=cls.owner)
        ProjectMembership.objects.create(project=cls.project, user=cls.owner, role="owner")
        ProjectMembership.objects.create(project=cls.project, user=cls.member)

    def post(self, **values):
        return service.save_post(self.owner, self.project, {"title": "Project decision", "body": "Discuss the next review.", **values})

    def auth(self, user, csrf=False):
        client = APIClient(enforce_csrf_checks=csrf)
        client.force_login(user)
        session = client.session; session[MFA_VERIFIED_SESSION_KEY] = timezone.now().isoformat(); session.save()
        return client

    def test_mentions_are_scoped_and_current_state_checked_for_both_channels(self):
        post = self.post(mention_ids=[self.member.pk])
        message = OutboundMessage.objects.get(user=self.member)
        self.assertTrue(message_eligible(message))
        self.assertEqual(UserAlert.objects.filter(user=self.member).count(), 1)
        with self.assertRaises(ValidationError): self.post(mention_ids=[self.outsider.pk])
        UserBlock.objects.create(user=self.member, blocked=self.owner)
        self.assertFalse(message_eligible(message))
        remove_stale_alerts()
        self.assertFalse(UserAlert.objects.exists())

    def test_announcement_pinning_membership_archive_and_concurrent_edit_guards(self):
        with self.assertRaises(PermissionDenied): service.save_post(self.member, self.project, {"title": "Team notice", "body": "Notice", "kind": "announcement"})
        with self.assertRaises(PermissionDenied): service.save_post(self.outsider, self.project, {"title": "Other post", "body": "Private"})
        post = self.post(pinned=True)
        updated = service.save_post(self.owner, self.project, {"body": "New decision", "expected_updated_at": post.updated_at}, post)
        with self.assertRaises(ValidationError): service.save_post(self.owner, self.project, {"body": "Old edit", "expected_updated_at": post.updated_at}, updated)
        self.project.archived_at = timezone.now(); self.project.save()
        with self.assertRaises(ValidationError): service.add_reply(self.member, updated, {"body": "Reply"})

    def test_reply_report_has_traceable_support_resolution_and_only_reported_content_can_be_hidden(self):
        post = self.post(); reply = service.add_reply(self.member, post, {"body": "Reported reply", "mention_ids": [self.owner.pk]})
        report = service.report_content(self.owner, post, "Privacy concern in reply", reply)
        with self.assertRaises(PermissionDenied): service.moderate_report(self.member, report, True, "Not authorised")
        self.owner.is_staff = True; self.owner.save(update_fields=["is_staff"])
        self.owner.user_permissions.add(Permission.objects.get(codename="moderate_reports"), Permission.objects.get(codename="manage_user_status"))
        # Permissions cached by earlier calls must not stand in for fresh state.
        self.owner = get_user_model().objects.get(pk=self.owner.pk)
        service.moderate_report(self.owner, report, True, "Removed the reported personal information")
        reply.refresh_from_db(); report.ticket.refresh_from_db()
        self.assertIsNotNone(reply.removed_at); self.assertEqual(report.ticket.status, "resolved")
        post.refresh_from_db(); self.assertIsNone(post.removed_at)
        with self.assertRaises(ValidationError): service.moderate_report(self.owner, report, True, "Duplicate decision")
        self.assertFalse(message_eligible(OutboundMessage.objects.get(target_id=reply.pk)))

    def test_listing_mfa_csrf_pagination_tombstones_and_immediate_membership_revocation(self):
        post = self.post(); service.add_reply(self.member, post, {"body": "Retained reply"})
        url = f"/api/v1/operations/projects/{self.project.pk}/posts/"
        client = APIClient(); self.assertEqual(client.get(url).status_code, 401)
        client.force_login(self.owner); self.assertEqual(client.get(url).status_code, 401)
        self.assertEqual(self.auth(self.outsider).get(url).status_code, 403)
        self.assertEqual(self.auth(self.member, csrf=True).post(url, {"title": "New post", "body": "Body"}, format="json").status_code, 403)
        self.assertEqual(self.auth(self.member).get(url).data["total"], 1)
        service.remove_content(self.owner, post)
        row = self.auth(self.member).get(url).data["results"][0]
        self.assertEqual(row["body"], ""); self.assertEqual(row["replies"][0]["body"], "")
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
        self.assertEqual(self.auth(self.member).get(url).status_code, 403)

    def test_member_cannot_remove_others_or_report_a_different_threads_reply(self):
        post = self.post(); other = self.post(title="Other decision")
        reply = service.add_reply(self.member, other, {"body": "Other reply"})
        with self.assertRaises(PermissionDenied): service.remove_content(self.member, post)
        with self.assertRaises(ValidationError): service.report_content(self.owner, post, "Wrong target", reply)
        service.remove_content(self.member, other, reply); reply.refresh_from_db()
        self.assertIsNotNone(reply.removed_at)

    def test_blocked_reminder_is_daily_deduplicated_and_stops_when_task_unblocks(self):
        now = timezone.now()
        task = Task.objects.create(project=self.project, created_by=self.owner, title="Long blocked task", status="blocked", blocker_note="Awaiting a review")
        Task.objects.filter(pk=task.pk).update(updated_at=now-timedelta(days=4)); task.refresh_from_db()
        TaskAssignment.objects.create(task=task, user=self.member, assigned_by=self.owner)
        schedule_blocked_tasks(now); schedule_blocked_tasks(now)
        self.assertEqual(UserAlert.objects.count(), 1)
        message = OutboundMessage.objects.get(); self.assertTrue(message_eligible(message))
        Task.objects.filter(pk=task.pk).update(status="in_progress", blocker_note="")
        self.assertFalse(message_eligible(message)); remove_stale_alerts(); self.assertFalse(UserAlert.objects.exists())
