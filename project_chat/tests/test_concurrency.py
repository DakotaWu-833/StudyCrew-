"""Chat transaction races cannot duplicate events or survive account closure."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from time import monotonic, sleep
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import OperationalError, close_old_connections, connections
from django.test import TransactionTestCase

from accounts.readiness_services import close_account
from operations.models import OperationAudit
from project_chat import services
from project_chat.models import ChatEvent, ChatMessage
from projects.models import Project, ProjectMembership


class ChatConcurrencyTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(email="chat-race-owner@example.com", password="Strong!Passphrase42", display_name="Chat race owner")
        self.member = User.objects.create_user(email="chat-race-member@example.com", password="Strong!Passphrase42", display_name="Chat race member")
        self.project = Project.objects.create(name="Concurrent chat team", created_by=self.owner)
        ProjectMembership.objects.create(project=self.project, user=self.owner, role="owner")
        ProjectMembership.objects.create(project=self.project, user=self.member)

    def concurrent(self, action):
        barrier = Barrier(2)

        def run(index):
            close_old_connections()
            barrier.wait(timeout=5)
            deadline = monotonic()+5
            try:
                while True:
                    try:
                        return action(index)
                    except OperationalError as error:
                        if "locked" not in str(error).lower() or monotonic() >= deadline:
                            raise
                        close_old_connections()
                        sleep(.02)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = [pool.submit(run, index) for index in range(2)]
            return [item.result(timeout=10) for item in pending]

    def test_simultaneous_identical_send_retries_create_one_message_and_event(self):
        nonce = uuid4()
        def action(index):
            actor = get_user_model().objects.get(pk=self.member.pk)
            _, created = services.send_message(actor, self.project.pk, body="One message despite parallel retry", client_nonce=nonce)
            return created
        self.assertCountEqual(self.concurrent(action), [True, False])
        self.assertEqual(ChatMessage.objects.count(), 1)
        self.assertEqual(ChatEvent.objects.count(), 1)

    def test_simultaneous_changed_payload_same_nonce_rejects_one(self):
        nonce = uuid4()
        def action(index):
            actor = get_user_model().objects.get(pk=self.member.pk)
            try:
                services.send_message(actor, self.project.pk, body=f"Conflicting parallel message {index}", client_nonce=nonce)
                return "sent"
            except ValidationError:
                return "rejected"
        self.assertCountEqual(self.concurrent(action), ["sent", "rejected"])
        self.assertEqual(ChatMessage.objects.count(), 1)
        self.assertEqual(ChatEvent.objects.count(), 1)

    def test_simultaneous_message_removal_creates_one_audit_and_one_removal_event(self):
        message, _ = services.send_message(self.member, self.project.pk, body="Remove only once", client_nonce=uuid4())
        def action(index):
            actor = get_user_model().objects.get(pk=self.member.pk)
            return services.remove_message(actor, self.project.pk, message.pk, expected_updated_at=message.updated_at, reason="Parallel removal request").pk
        self.assertEqual(self.concurrent(action), [message.pk, message.pk])
        self.assertEqual(OperationAudit.objects.filter(action="chat_message_removed", target_id=message.pk).count(), 1)
        self.assertEqual(ChatEvent.objects.count(), 2)

    def test_send_racing_account_close_leaves_no_private_content_or_current_membership(self):
        def action(index):
            actor = get_user_model().objects.get(pk=self.member.pk)
            if index == 0:
                try:
                    services.send_message(actor, self.project.pk, body="Sensitive race content", client_nonce=uuid4())
                    return "sent"
                except PermissionDenied:
                    return "denied"
            close_account(user=actor, confirmation="CLOSE MY ACCOUNT")
            return "closed"
        result = self.concurrent(action)
        self.assertIn(result[0], {"sent", "denied"})
        self.assertEqual(result[1], "closed")
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertFalse(ChatMessage.objects.exclude(body="").exists())
        self.assertFalse(ProjectMembership.objects.active().filter(user=self.member).exists())
        for row in services.conversation(self.owner, self.project.pk)["messages"]:
            self.assertEqual(row["body"], "")
            self.assertTrue(row["removed"])
            self.assertEqual(row["author"]["display_name"], "Closed account")
