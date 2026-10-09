"""Private chat behavior, reconnect pagination, and lifecycle boundaries."""
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.http import Http404
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.readiness_services import close_account
from api.tests.base import APIDomainTestCase
from operations.models import OperationAudit, UserBlock
from project_chat import services
from project_chat.models import ChatEvent, ChatMessage, ChatPresence
from projects.models import Project, ProjectMembership


@override_settings(OPERATIONS_RATE_LIMITS=False)
class ProjectConversationTests(APIDomainTestCase):
    def url(self, suffix="messages/"):
        return f"/api/v1/chat/projects/{self.project.pk}/{suffix}"

    def message(self, author=None, body="Private conversation"):
        return services.send_message(author or self.owner, self.project.pk, body=body, client_nonce=uuid4())[0]

    def bulk_messages(self, count):
        messages = [ChatMessage(project=self.project, author=self.owner, client_nonce=uuid4(), body=f"Message {index}") for index in range(count)]
        ChatMessage.objects.bulk_create(messages)
        ChatEvent.objects.bulk_create([ChatEvent(project=self.project, message=message) for message in messages])
        return messages

    def test_api_requires_mfa_and_current_membership(self):
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.url()).status_code, 401)
        self.authenticate(self.outsider)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(self.project.name, response.content.decode())
        self.assertEqual(self.client.post(self.url(), {"body": "Attempted intrusion", "client_nonce": str(uuid4())}, format="json").status_code, 403)
        self.assertEqual(self.client.post(self.url("presence/"), {}, format="json").status_code, 403)
        self.assertFalse(ChatMessage.objects.exists())
        self.assertFalse(ChatPresence.objects.exists())

    def test_browser_csrf_is_required_and_valid_cookie_allows_send(self):
        client = APIClient(enforce_csrf_checks=True)
        self.authenticate(self.owner, client=client)
        payload = {"body": "CSRF protected message", "client_nonce": str(uuid4())}
        self.assertEqual(client.post(self.url(), payload, format="json").status_code, 403)
        self.assertFalse(ChatMessage.objects.exists())
        self.assertEqual(client.get("/account/profile/").status_code, 200)
        response = client.post(self.url(), payload, format="json", HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(response.status_code, 201, response.content)

    def test_send_retry_is_exactly_once_and_changed_nonce_payload_rejected(self):
        self.authenticate(self.member)
        payload = {"body": "I have uploaded the draft.", "client_nonce": str(uuid4())}
        first = self.client.post(self.url(), payload, format="json")
        retry = self.client.post(self.url(), payload, format="json")
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(first.json()["id"], retry.json()["id"])
        altered = self.client.post(self.url(), {**payload, "body": "Different message"}, format="json")
        self.assertEqual(altered.status_code, 400)
        self.assertEqual(ChatMessage.objects.count(), 1)
        self.assertEqual(ChatEvent.objects.count(), 1)

    def test_nonce_is_scoped_to_author_and_cannot_move_between_projects(self):
        nonce = uuid4()
        first, _ = services.send_message(self.owner, self.project.pk, body="Shared nonce", client_nonce=nonce)
        second, _ = services.send_message(self.member, self.project.pk, body="Shared nonce", client_nonce=nonce)
        self.assertNotEqual(first.pk, second.pk)
        other = Project.objects.create(name="Other private team", created_by=self.owner)
        ProjectMembership.objects.create(project=other, user=self.owner, role="owner")
        with self.assertRaises(ValidationError):
            services.send_message(self.owner, other.pk, body="Shared nonce", client_nonce=nonce)
        self.assertEqual(ChatMessage.objects.count(), 2)

    def test_strict_inputs_reject_empty_long_body_invalid_cursor_and_extra_fields(self):
        self.authenticate(self.owner)
        for payload in [{"body": " ", "client_nonce": str(uuid4())}, {"body": "x" * 2001, "client_nonce": str(uuid4())}, {"body": "Valid message", "client_nonce": str(uuid4()), "author": str(self.member.pk)}]:
            with self.subTest(payload=list(payload)):
                self.assertEqual(self.client.post(self.url(), payload, format="json").status_code, 400)
        self.assertEqual(self.client.get(self.url(), {"since": -1}).status_code, 400)
        self.assertEqual(self.client.get(self.url(), {"since": 0, "before": str(uuid4())}).status_code, 400)
        self.assertFalse(ChatMessage.objects.exists())

    def test_removed_members_cannot_read_send_remove_or_publish_presence(self):
        message = self.message(self.member)
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
        for operation in [lambda: services.conversation(self.member, self.project.pk), lambda: services.send_message(self.member, self.project.pk, body="Former member", client_nonce=uuid4()), lambda: services.heartbeat(self.member, self.project.pk), lambda: services.remove_message(self.member, self.project.pk, message.pk, expected_updated_at=message.updated_at, reason="Withdraw this message")]:
            with self.assertRaises(PermissionDenied):
                operation()
        message.refresh_from_db()
        self.assertIsNone(message.removed_at)

    def test_closed_or_inactive_database_identity_overrides_stale_loaded_user(self):
        for changes in [{"closed_at": timezone.now()}, {"is_active": False}]:
            get_user_model().objects.filter(pk=self.member.pk).update(**changes)
            for operation in [lambda: services.conversation(self.member, self.project.pk), lambda: services.send_message(self.member, self.project.pk, body="Stale identity", client_nonce=uuid4()), lambda: services.heartbeat(self.member, self.project.pk)]:
                with self.assertRaises(PermissionDenied):
                    operation()
            get_user_model().objects.filter(pk=self.member.pk).update(closed_at=None, is_active=True)
        self.assertFalse(ChatMessage.objects.exists())

    def test_archived_project_retains_readable_history_but_is_not_writable(self):
        message = self.message()
        self.project.archived_at = timezone.now()
        self.project.save(update_fields=["archived_at"])
        result = services.conversation(self.member, self.project.pk)
        self.assertTrue(result["read_only"])
        self.assertEqual(result["messages"][0]["body"], message.body)
        with self.assertRaises(ValidationError):
            services.send_message(self.owner, self.project.pk, body="Cannot write", client_nonce=uuid4())
        with self.assertRaises(ValidationError):
            services.remove_message(self.owner, self.project.pk, message.pk, expected_updated_at=message.updated_at, reason="Cannot remove")
        services.heartbeat(self.owner, self.project.pk)
        self.assertFalse(ChatPresence.objects.exists())

    def test_older_message_pagination_has_no_gaps_or_duplicates_with_equal_times(self):
        messages = self.bulk_messages(123)
        ChatMessage.objects.filter(project=self.project).update(created_at=timezone.now())
        ids, page = [], services.conversation(self.member, self.project.pk)
        while True:
            ids = [row["id"] for row in page["messages"]] + ids
            self.assertLessEqual(len(page["messages"]), 50)
            if not page["has_more"]:
                self.assertIsNone(page["older_than"])
                break
            page = services.conversation(self.member, self.project.pk, before=page["older_than"])
        self.assertEqual(len(ids), 123)
        self.assertEqual(len(set(ids)), 123)
        self.assertEqual(set(ids), {str(message.pk) for message in messages})

    def test_older_cursor_cannot_reference_message_from_another_project(self):
        other = Project.objects.create(name="Private other team", created_by=self.owner)
        anchor = ChatMessage.objects.create(project=other, author=self.owner, client_nonce=uuid4(), body="Secret other conversation")
        with self.assertRaises(Http404):
            services.conversation(self.member, self.project.pk, before=anchor.pk)

    def test_reconnect_drains_more_than_one_hundred_events_and_receives_old_removal(self):
        messages = self.bulk_messages(125)
        first = services.conversation(self.member, self.project.pk, since=0)
        self.assertEqual(len(first["messages"]), 100)
        self.assertTrue(first["has_more"])
        second = services.conversation(self.member, self.project.pk, since=first["cursor"])
        self.assertEqual(len(second["messages"]), 25)
        self.assertFalse(second["has_more"])
        self.assertGreater(second["cursor"], first["cursor"])
        self.assertEqual({row["id"] for row in first["messages"] + second["messages"]}, {str(message.pk) for message in messages})
        oldest = messages[0]
        services.remove_message(self.owner, self.project.pk, oldest.pk, expected_updated_at=oldest.updated_at, reason="Sensitive content removed")
        reconnect = services.conversation(self.member, self.project.pk, since=second["cursor"])
        self.assertEqual(len(reconnect["messages"]), 1)
        self.assertEqual(reconnect["messages"][0]["id"], str(oldest.pk))
        self.assertTrue(reconnect["messages"][0]["removed"])
        self.assertEqual(reconnect["messages"][0]["body"], "")

    def test_reconnect_collapses_multiple_events_for_same_message(self):
        message = self.message()
        services.remove_message(self.owner, self.project.pk, message.pk, expected_updated_at=message.updated_at, reason="Withdraw this message")
        reconnect = services.conversation(self.member, self.project.pk, since=0)
        self.assertEqual(len(reconnect["messages"]), 1)
        self.assertTrue(reconnect["messages"][0]["removed"])
        self.assertEqual(reconnect["cursor"], ChatEvent.objects.order_by("-id").first().pk)

    def test_online_presence_excludes_expired_removed_closed_and_blocked_users(self):
        users = [self.member]
        for index in range(4):
            user = get_user_model().objects.create_user(email=f"chat-presence-{index}@example.com", password=self.password, display_name=f"Presence {index}")
            ProjectMembership.objects.create(project=self.project, user=user)
            users.append(user)
        now = timezone.now()
        ChatPresence.objects.bulk_create([ChatPresence(project=self.project, user=user, last_seen_at=now) for user in users])
        ChatPresence.objects.filter(user=users[1]).update(last_seen_at=now-timedelta(seconds=36))
        ProjectMembership.objects.filter(project=self.project, user=users[2]).update(removed_at=now)
        get_user_model().objects.filter(pk=users[3].pk).update(closed_at=now)
        UserBlock.objects.create(user=users[4], blocked=self.owner)
        result = services.conversation(self.owner, self.project.pk)
        self.assertEqual([row["id"] for row in result["online"]], [str(self.member.pk)])

    def test_blocking_either_direction_hides_content_and_updates_visibility_key(self):
        self.message(self.member, "Private member text")
        visible = services.conversation(self.owner, self.project.pk)
        self.assertEqual(visible["visibility_key"], "")
        for blocker, blocked in [(self.owner, self.member), (self.member, self.owner)]:
            block = UserBlock.objects.create(user=blocker, blocked=blocked)
            result = services.conversation(self.owner, self.project.pk)
            self.assertEqual(result["visibility_key"], str(self.member.pk))
            self.assertEqual(result["messages"][0]["body"], "")
            self.assertTrue(result["messages"][0]["hidden"])
            self.assertFalse(result["messages"][0]["can_remove"])
            block.delete()
        self.assertEqual(services.conversation(self.owner, self.project.pk)["messages"][0]["body"], "Private member text")

    def test_author_or_facilitator_can_remove_but_other_member_cannot(self):
        message = self.message()
        with self.assertRaises(PermissionDenied):
            services.remove_message(self.member, self.project.pk, message.pk, expected_updated_at=message.updated_at, reason="Unpermitted removal")
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(role="facilitator")
        services.remove_message(self.member, self.project.pk, message.pk, expected_updated_at=message.updated_at, reason="Confirmed privacy concern")
        audit = OperationAudit.objects.get(action="chat_message_removed", target_id=message.pk)
        self.assertEqual(audit.actor, self.member)
        self.assertEqual(audit.metadata["reason"], "Confirmed privacy concern")
        message.refresh_from_db()
        self.assertEqual(message.body, "")
        repeated = services.remove_message(self.owner, self.project.pk, message.pk, expected_updated_at=message.created_at, reason="Repeat removal")
        self.assertEqual(repeated.pk, message.pk)
        self.assertEqual(OperationAudit.objects.filter(action="chat_message_removed").count(), 1)
        self.assertEqual(ChatEvent.objects.count(), 2)

    def test_stale_remove_and_cross_project_message_reject_without_audit(self):
        message = self.message(self.member)
        with self.assertRaises(ValidationError):
            services.remove_message(self.member, self.project.pk, message.pk, expected_updated_at=message.updated_at-timedelta(seconds=1), reason="Stale deletion")
        other = Project.objects.create(name="Different private team", created_by=self.owner)
        foreign = ChatMessage.objects.create(project=other, author=self.owner, client_nonce=uuid4(), body="Other team message")
        with self.assertRaises(Http404):
            services.remove_message(self.owner, self.project.pk, foreign.pk, expected_updated_at=foreign.updated_at, reason="Wrong project")
        self.assertFalse(OperationAudit.objects.filter(action="chat_message_removed").exists())

    def test_conversation_query_count_is_bounded_when_page_grows_to_fifty(self):
        self.bulk_messages(1)
        with CaptureQueriesContext(connection) as one:
            services.conversation(self.member, self.project.pk)
        self.bulk_messages(49)
        with CaptureQueriesContext(connection) as fifty:
            result = services.conversation(self.member, self.project.pk)
        self.assertEqual(len(result["messages"]), 50)
        self.assertEqual(len(one), len(fifty))
        self.assertLessEqual(len(fifty), 14)
        with CaptureQueriesContext(connection) as reconnect:
            services.conversation(self.member, self.project.pk, since=0)
        self.assertLessEqual(len(reconnect), 14)

    def test_personal_export_withholds_former_project_body_and_never_other_authors(self):
        own = self.message(self.member, "Authored private content")
        self.message(self.owner, "Owner private content")
        data = services.personal_data(self.member)
        self.assertEqual([row["id"] for row in data], [str(own.pk)])
        self.assertEqual(data[0]["body"], own.body)
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
        data = services.personal_data(self.member)
        self.assertTrue(data[0]["content_withheld"])
        self.assertIsNone(data[0]["body"])
        self.assertNotIn("Owner private content", str(data))

    def test_account_closure_scrubs_historical_messages_and_emits_reconnect_event(self):
        message = self.message(self.member, "Remove my historical private text")
        services.heartbeat(self.member, self.project.pk)
        cursor = services.conversation(self.owner, self.project.pk)["cursor"]
        ProjectMembership.objects.filter(project=self.project, user=self.member).update(removed_at=timezone.now())
        close_account(user=self.member, confirmation="CLOSE MY ACCOUNT")
        message.refresh_from_db()
        self.assertEqual(message.body, "")
        self.assertIsNotNone(message.removed_at)
        self.assertFalse(ChatPresence.objects.filter(user=self.member).exists())
        result = services.conversation(self.owner, self.project.pk, since=cursor)
        self.assertEqual(result["messages"][0]["author"]["display_name"], "Closed account")
        self.assertEqual(result["messages"][0]["body"], "")
        self.assertTrue(result["messages"][0]["removed"])
        with self.assertRaises(PermissionDenied):
            services.conversation(self.member, self.project.pk)

    @override_settings(OPERATIONS_RATE_LIMITS=True)
    def test_throttled_send_and_presence_do_not_create_records(self):
        self.authenticate(self.owner)
        with patch("project_chat.views.consume_rate", return_value=False):
            self.assertEqual(self.client.post(self.url(), {"body": "Throttled message", "client_nonce": str(uuid4())}, format="json").status_code, 429)
            self.assertEqual(self.client.post(self.url("presence/"), {}, format="json").status_code, 429)
        self.assertFalse(ChatMessage.objects.exists())
        self.assertFalse(ChatEvent.objects.exists())
        self.assertFalse(ChatPresence.objects.exists())
