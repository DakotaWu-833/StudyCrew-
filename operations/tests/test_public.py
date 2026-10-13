import hashlib
import hmac
import json
import re
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from django.core import mail
from django.db import DatabaseError
from django.test import Client, override_settings
from django.utils import timezone

from operations.models import ContactRequest, OutboundMessage, SuppressedAddress, WebhookReceipt, WorkerHeartbeat
from operations.services import enqueue_email
from .helpers import OperationsTestCase


class PublicSupportTests(OperationsTestCase):
    def request_help(self, email="recover@example.com", **extra):
        return self.client.post("/help/", {
            "email": email, "category": "appeal", "subject": "Need account access",
            "description": "My university email expired. Please review recovery options.",
        }, **extra)

    def link(self):
        return urlsplit(re.search(r"https?://[^\s]+", mail.outbox[-1].body).group(0)).path

    def test_public_support_works_without_login_and_persists_only_token_digest(self):
        response = self.request_help()
        self.assertEqual(response.status_code, 200)
        row = ContactRequest.objects.get()
        self.assertIsNone(row.verified_at)
        self.assertEqual(len(row.verification_hash), 64)
        token = self.link().strip("/").rsplit("/", 1)[-1]
        self.assertNotIn(token, row.verification_hash)
        self.assertEqual(mail.outbox[-1].to, ["recover@example.com"])
        self.assertIn("https://studycrew.example/help/verify/", mail.outbox[-1].body)

    def test_mail_scanner_get_does_not_confirm_and_post_requires_csrf(self):
        self.request_help()
        strict = Client(enforce_csrf_checks=True)
        response = strict.get(self.link())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(response["Referrer-Policy"], "strict-origin")
        self.assertIsNone(ContactRequest.objects.get().verified_at)
        self.assertEqual(strict.post(self.link()).status_code, 403)
        csrf = strict.cookies["csrftoken"].value
        confirmed = strict.post(self.link(), HTTP_X_CSRFTOKEN=csrf)
        self.assertContains(confirmed, "Request confirmed")
        row = ContactRequest.objects.get()
        first = row.verified_at
        self.assertIsNotNone(first)
        self.assertEqual(row.verification_hash, "")
        strict.post(self.link(), HTTP_X_CSRFTOKEN=csrf)
        row.refresh_from_db()
        self.assertEqual(row.verified_at, first)

    def test_forged_expired_and_reused_support_links_cannot_confirm(self):
        self.request_help()
        original = self.link()
        forged = original.rstrip("/").rsplit("/", 1)[0] + "/forged/"
        self.client.post(forged)
        self.assertIsNone(ContactRequest.objects.get().verified_at)
        ContactRequest.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        expired = self.client.post(original)
        self.assertContains(expired, "Confirmation unavailable")
        self.assertIsNone(ContactRequest.objects.get().verified_at)

    def test_support_request_is_csrf_protected_and_invalid_fields_send_no_mail(self):
        self.assertEqual(Client(enforce_csrf_checks=True).post("/help/", {"email": "person@example.com"}).status_code, 403)
        response = self.client.post("/help/", {"email": "invalid", "category": "privacy", "subject": "Help", "description": "Please review."})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ContactRequest.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_support_limits_ip_and_email_with_uniform_feedback(self):
        responses = [self.request_help(email=f"person{index}@example.com") for index in range(7)]
        self.assertEqual(ContactRequest.objects.count(), 5)
        for response in responses:
            self.assertContains(response, "If we can send to that address")
        self.assertEqual(len(mail.outbox), 5)

    def test_support_email_limit_normalises_case_and_ignores_ip_rotation(self):
        for index in range(5):
            self.request_help(email="Case@Example.com" if index % 2 else "case@example.com", REMOTE_ADDR=f"10.0.0.{index + 1}")
        self.assertEqual(ContactRequest.objects.count(), 3)
        self.assertEqual(len(mail.outbox), 3)

    def test_support_delivery_failure_is_generic_and_removes_unverified_request(self):
        with patch("operations.public_views.send_mail", side_effect=OSError("secret mail detail")):
            response = self.request_help()
        self.assertContains(response, "If we can send to that address")
        self.assertNotContains(response, "secret mail detail")
        self.assertFalse(ContactRequest.objects.exists())


@override_settings(MAIL_WEBHOOK_SECRET="a-test-only-signed-event-secret")
class MailWebhookTests(OperationsTestCase):
    def setUp(self):
        self.message = self.message(status="accepted", accepted_at=timezone.now())

    def event(self, event="delivered", *, timestamp=None, body=None, signature=None, identifier=None):
        timestamp = str(timestamp if timestamp is not None else int(timezone.now().timestamp()))
        body = body if body is not None else json.dumps({"message_id": str(identifier or self.message.pk), "event": event}).encode()
        signature = signature or hmac.new(b"a-test-only-signed-event-secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return self.client.post("/delivery/events/", data=body, content_type="application/json",
            HTTP_X_STUDYCREW_TIMESTAMP=timestamp, HTTP_X_STUDYCREW_SIGNATURE=signature)

    def test_valid_delivery_is_confirmed_and_exact_replay_is_idempotent(self):
        instant = int(timezone.now().timestamp())
        self.assertEqual(self.event(timestamp=instant).status_code, 200)
        self.message.refresh_from_db()
        confirmed = self.message.confirmed_at
        self.assertEqual(self.message.status, "delivered")
        self.assertIsNotNone(confirmed)
        self.assertEqual(self.event(timestamp=instant).status_code, 200)
        self.message.refresh_from_db()
        self.assertEqual(self.message.confirmed_at, confirmed)
        self.assertEqual(WebhookReceipt.objects.count(), 1)

    def test_bounce_suppresses_and_terminal_replays_cannot_restore_delivery(self):
        instant = int(timezone.now().timestamp())
        self.assertEqual(self.event("bounced", timestamp=instant).status_code, 200)
        self.assertTrue(SuppressedAddress.objects.filter(email=self.member.email, reason="bounce").exists())
        self.assertEqual(self.event("bounced", timestamp=instant + 1).status_code, 200)
        self.assertEqual(self.event("delivered", timestamp=instant + 2).status_code, 200)
        self.message.refresh_from_db()
        self.assertEqual(self.message.status, "bounced")
        self.assertIsNone(enqueue_email(recipient=self.member.email, subject="Another", body="Detail", key="after-bounce", user=self.member))

    def test_complaint_suppresses_and_prevents_later_delivered_event(self):
        instant = int(timezone.now().timestamp())
        self.assertEqual(self.event("complained", timestamp=instant).status_code, 200)
        self.assertEqual(self.event("delivered", timestamp=instant + 1).status_code, 200)
        self.message.refresh_from_db()
        self.assertEqual(self.message.status, "complained")
        self.assertTrue(SuppressedAddress.objects.filter(email=self.member.email, reason="complaint").exists())

    def test_unsigned_wrong_signature_and_old_timestamps_do_not_mutate_mail(self):
        self.assertEqual(self.client.post("/delivery/events/", data=b"{}", content_type="application/json").status_code, 401)
        self.assertEqual(self.event(signature="forged").status_code, 401)
        self.assertEqual(self.event(timestamp=int(timezone.now().timestamp()) - 600).status_code, 401)
        self.assertEqual(self.event(timestamp="not-an-integer").status_code, 401)
        self.message.refresh_from_db()
        self.assertEqual(self.message.status, "accepted")
        self.assertFalse(WebhookReceipt.objects.exists())

    def test_malformed_payload_wrong_id_event_and_not_accepted_message_are_rejected(self):
        for body in (b"not-json", b"[]", b'{"message_id":"bad","event":"delivered"}', b'{"message_id":"bad","event":"unexpected"}'):
            self.assertEqual(self.event(body=body).status_code, 400)
        self.assertEqual(self.event(identifier=uuid4()).status_code, 404)
        self.message.status = "queued"
        self.message.save(update_fields=["status"])
        self.assertEqual(self.event().status_code, 404)
        self.assertFalse(WebhookReceipt.objects.exists())

    def test_oversized_payload_and_unconfigured_adapter_are_refused(self):
        self.assertEqual(self.event(body=b"x" * 8193).status_code, 403)
        with override_settings(MAIL_WEBHOOK_SECRET=""):
            self.assertEqual(self.event().status_code, 403)


class ReadinessHealthTests(OperationsTestCase):
    def test_health_requires_recent_worker_and_is_public_without_internal_data(self):
        missing = self.client.get("/health/")
        self.assertEqual(missing.status_code, 503)
        WorkerHeartbeat.objects.create(name="delivery", last_run_at=timezone.now())
        ready = self.client.get("/health/")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json(), {"status": "ready"})
        self.assertEqual(ready["Cache-Control"], "no-store")
        self.assertEqual(self.client.head("/health/").status_code, 200)
        self.assertEqual(self.client.post("/health/").status_code, 405)
        WorkerHeartbeat.objects.update(last_run_at=timezone.now() - timedelta(minutes=6))
        self.assertEqual(self.client.get("/health/").status_code, 503)

    def test_health_degrades_on_maintenance_and_database_failure(self):
        WorkerHeartbeat.objects.create(name="delivery", last_run_at=timezone.now())
        with override_settings(MAINTENANCE_MODE=True):
            self.assertEqual(self.client.get("/health/").status_code, 503)
        with patch("operations.public_views.connection.cursor", side_effect=DatabaseError("private database detail")):
            response = self.client.get("/health/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})
