"""Deterministic interleavings of SMTP, callback, cancellation and lease expiry."""
import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.db import DatabaseError
from django.db.models.query import QuerySet
from django.utils import timezone

from accounts.readiness_services import close_account
from operations.models import OutboundMessage, SuppressedAddress, WebhookReceipt
from operations.services import update_preferences
from operations.worker import process_outbound
from .helpers import OperationsTestCase


@override_settings(MAIL_WEBHOOK_SECRET="interleaving-test-secret")
class DeliveryInterleavingTests(OperationsTestCase):
    def callback(self, message, event="delivered"):
        timestamp = str(int(timezone.now().timestamp()))
        body = json.dumps({"message_id": str(message.pk), "event": event}).encode()
        signature = hmac.new(b"interleaving-test-secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return self.client.post("/delivery/events/", data=body, content_type="application/json",
            HTTP_X_STUDYCREW_TIMESTAMP=timestamp, HTTP_X_STUDYCREW_SIGNATURE=signature)

    def test_provider_result_arriving_during_smtp_survives_success_or_transport_error(self):
        for event in ("delivered", "bounced", "complained"):
            for transport_fails in (False, True):
                with self.subTest(event=event, transport_fails=transport_fails):
                    SuppressedAddress.objects.all().delete()
                    message = self.message()

                    def transport(**kwargs):
                        message.refresh_from_db()
                        self.assertEqual(message.status, "processing")
                        self.assertEqual(message.attempts, 1)
                        self.assertEqual(self.callback(message, event).status_code, 200)
                        if transport_fails:
                            raise OSError("response lost after provider accepted mail")

                    with patch("operations.worker.send_outbound_message", side_effect=transport) as send:
                        process_outbound()
                        process_outbound()
                    self.assertEqual(send.call_count, 1)
                    message.refresh_from_db()
                    self.assertEqual(message.status, event)
                    self.assertEqual(message.attempts, 1)
                    self.assertIsNotNone(message.confirmed_at)
                    self.assertIsNone(message.locked_at)
                    self.assertEqual(message.failure_reason, "")

    def test_closing_account_while_smtp_is_in_flight_remains_cancelled(self):
        message = self.message()

        def transport(**kwargs):
            close_account(user=self.member, confirmation="CLOSE MY ACCOUNT")

        with patch("operations.worker.send_outbound_message", side_effect=transport) as send:
            process_outbound()
            process_outbound()
        self.assertEqual(send.call_count, 1)
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        message.refresh_from_db()
        self.assertEqual(message.status, "cancelled")
        self.assertEqual(message.failure_reason, "Account closed")
        self.assertEqual(message.attempts, 1)
        self.assertEqual(self.callback(message, "delivered").status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.status, "cancelled")

    def test_transport_error_cannot_requeue_cancelled_mail_and_late_bounce_suppresses(self):
        message = self.message()

        def transport(**kwargs):
            OutboundMessage.objects.filter(pk=message.pk).update(status="cancelled", failure_reason="Account closed")
            raise OSError("transport interrupted")

        with patch("operations.worker.send_outbound_message", side_effect=transport) as send:
            process_outbound()
            process_outbound()
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.callback(message, "bounced").status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.status, "cancelled")
        self.assertEqual(message.failure_reason, "Account closed")
        self.assertTrue(SuppressedAddress.objects.filter(email=message.recipient, reason="bounce").exists())

    def test_old_worker_cannot_overwrite_an_expired_and_retried_lease(self):
        message = self.message()

        def old_transport(**kwargs):
            # A second worker recovers the interrupted lease, then the operator
            # explicitly retries it. The new attempt completes before the
            # original SMTP connection finally reports failure.
            OutboundMessage.objects.filter(pk=message.pk).update(locked_at=timezone.now() - timedelta(minutes=20))
            process_outbound(limit=0)
            message.refresh_from_db()
            self.assertEqual(message.status, "failed")
            self.assertIn("uncertain", message.failure_reason)
            OutboundMessage.objects.filter(pk=message.pk).update(status="queued", attempts=0, available_at=timezone.now())
            with patch("operations.worker.send_outbound_message") as new_transport:
                self.assertEqual(process_outbound()["accepted"], 1)
            self.assertEqual(new_transport.call_count, 1)
            raise OSError("old connection failed after the new attempt completed")

        with patch("operations.worker.send_outbound_message", side_effect=old_transport) as send:
            process_outbound()
        self.assertEqual(send.call_count, 1)
        message.refresh_from_db()
        self.assertEqual(message.status, "accepted")
        self.assertEqual(message.attempts, 1)
        self.assertEqual(message.failure_reason, "")
        self.assertIsNone(message.locked_at)

    def test_late_provider_result_settles_retry_or_uncertain_failure_without_resending(self):
        for status in ("queued", "failed"):
            with self.subTest(status=status):
                message = self.message(status=status, attempts=1,
                    failure_reason="Delivery outcome uncertain after worker interruption.")
                self.assertEqual(self.callback(message).status_code, 200)
                with patch("operations.worker.send_outbound_message") as send:
                    process_outbound()
                send.assert_not_called()
                message.refresh_from_db()
                self.assertEqual(message.status, "delivered")
                self.assertEqual(message.failure_reason, "")

    def test_never_attempted_queued_or_processing_mail_cannot_be_confirmed(self):
        for status in ("queued", "processing", "failed"):
            with self.subTest(status=status):
                message = self.message(status=status, attempts=0)
                self.assertEqual(self.callback(message).status_code, 404)
                message.refresh_from_db()
                self.assertEqual(message.status, status)
        self.assertFalse(WebhookReceipt.objects.exists())

    def test_preparation_failure_is_bounded_and_never_enters_transport(self):
        update_preferences(self.member, {"digest": "daily"})
        message = self.message()
        message.target_type = "digest"
        message.save(update_fields=["target_type"])
        with patch("operations.worker.digest_body", side_effect=ValueError("private generation detail")), patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["failed"], 1)
            process_outbound()
        send.assert_not_called()
        message.refresh_from_db()
        self.assertEqual(message.status, "failed")
        self.assertEqual(message.attempts, 0)
        self.assertEqual(message.failure_reason, "Mail preparation unavailable.")

    def test_cancellation_during_body_preparation_prevents_transport(self):
        update_preferences(self.member, {"digest": "daily"})
        message = self.message()
        message.target_type = "digest"
        message.save(update_fields=["target_type"])

        def prepare(user):
            OutboundMessage.objects.filter(pk=message.pk).update(status="cancelled")
            return "Prepared digest"

        with patch("operations.worker.digest_body", side_effect=prepare), patch("operations.worker.send_outbound_message") as send:
            process_outbound()
        send.assert_not_called()
        message.refresh_from_db()
        self.assertEqual(message.status, "cancelled")
        self.assertEqual(message.attempts, 0)

    def test_database_failure_after_smtp_success_remains_uncertain_without_auto_resend(self):
        message = self.message()
        original_update = QuerySet.update

        def update(queryset, **changes):
            if queryset.model is OutboundMessage and changes.get("status") == "accepted":
                raise DatabaseError("acceptance could not be saved")
            return original_update(queryset, **changes)

        with patch.object(QuerySet, "update", autospec=True, side_effect=update), patch("operations.worker.send_outbound_message") as send:
            with self.assertRaises(DatabaseError):
                process_outbound()
        self.assertEqual(send.call_count, 1)
        message.refresh_from_db()
        self.assertEqual(message.status, "processing")
        self.assertEqual(message.attempts, 1)
        OutboundMessage.objects.filter(pk=message.pk).update(locked_at=timezone.now() - timedelta(minutes=20))
        with patch("operations.worker.send_outbound_message") as retry:
            process_outbound()
        retry.assert_not_called()
        message.refresh_from_db()
        self.assertEqual(message.status, "failed")
        self.assertIn("uncertain", message.failure_reason)

