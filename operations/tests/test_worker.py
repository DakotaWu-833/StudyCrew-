import tempfile
from datetime import time, timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import override_settings
from django.utils import timezone

from activity.exports import export_file_for_user, request_export
from activity.models import ExportJob
from operations.models import OutboundMessage, UserAlert
from operations.services import update_preferences
from operations.worker import cleanup_expired_files, process_exports, process_outbound, remove_stale_alerts
from projects.models import ProjectMembership
from tasks.models import Task
from .helpers import OperationsTestCase


class DeliveryWorkerTests(OperationsTestCase):
    def test_mail_acceptance_is_recorded_separately_from_delivery_confirmation(self):
        message = self.message()
        with patch("operations.worker.send_outbound_message") as send:
            outcomes = process_outbound()
        message.refresh_from_db()
        self.assertEqual(outcomes["accepted"], 1)
        self.assertEqual(message.status, "accepted")
        self.assertEqual(message.attempts, 1)
        self.assertIsNotNone(message.accepted_at)
        self.assertIsNone(message.confirmed_at)
        self.assertEqual(send.call_args.kwargs["recipient"], self.member.email)
        with patch("operations.worker.send_outbound_message") as duplicate:
            process_outbound()
        duplicate.assert_not_called()

    def test_revoked_membership_cancels_before_transport_is_called(self):
        message = self.message()
        ProjectMembership.objects.filter(pk=self.membership.pk).update(removed_at=timezone.now())
        with patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["cancelled"], 1)
        send.assert_not_called()
        message.refresh_from_db()
        self.assertEqual(message.status, "cancelled")

    def test_email_change_and_account_closure_cancel_stale_recipient_messages(self):
        message = self.message()
        self.member.email = "new@example.com"
        self.member.save(update_fields=["email"])
        with patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["cancelled"], 1)
        send.assert_not_called()
        message.refresh_from_db()
        self.assertEqual(message.status, "cancelled")
        message.status = "queued"
        message.recipient = self.member.email
        message.save(update_fields=["status", "recipient"])
        self.member.is_active = False
        self.member.closed_at = timezone.now()
        self.member.save(update_fields=["is_active", "closed_at"])
        with patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["cancelled"], 1)
        send.assert_not_called()

    def test_archived_project_cancels_stale_mail(self):
        self.message()
        self.project.archived_at = timezone.now()
        self.project.save(update_fields=["archived_at"])
        with patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["cancelled"], 1)
        send.assert_not_called()

    def test_transport_retries_have_exponential_delay_and_stop_after_four_attempts(self):
        message = self.message()
        with patch("operations.worker.send_outbound_message", side_effect=OSError("secret transport detail")) as send:
            for attempt in range(1, 5):
                OutboundMessage.objects.filter(pk=message.pk).update(available_at=timezone.now() - timedelta(seconds=1))
                outcomes = process_outbound()
                message.refresh_from_db()
                self.assertEqual(message.attempts, attempt)
                self.assertEqual(message.failure_reason, "Mail transport unavailable.")
                if attempt < 4:
                    self.assertEqual(message.status, "queued")
                    self.assertGreater(message.available_at, timezone.now() + timedelta(minutes=2 ** attempt) - timedelta(seconds=3))
                    self.assertEqual(outcomes["deferred"], 1)
                else:
                    self.assertEqual(message.status, "failed")
                    self.assertEqual(outcomes["failed"], 1)
            self.assertEqual(send.call_count, 4)
            process_outbound()
            self.assertEqual(send.call_count, 4)

    def test_stale_processing_lease_is_failed_without_automatic_resend(self):
        message = self.message(status="processing", locked_at=timezone.now() - timedelta(minutes=20))
        with patch("operations.worker.send_outbound_message") as send:
            process_outbound()
        message.refresh_from_db()
        self.assertEqual(message.status, "failed")
        self.assertIn("uncertain", message.failure_reason)
        send.assert_not_called()

    def test_quiet_hours_defer_delivery_and_security_bypasses_them(self):
        message = self.message()
        until = timezone.now() + timedelta(hours=2)
        with patch("operations.worker.quiet_until", return_value=until), patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["deferred"], 1)
        send.assert_not_called()
        message.refresh_from_db()
        self.assertEqual(message.status, "queued")
        self.assertEqual(message.available_at, until)
        security = OutboundMessage.objects.create(user=self.member, recipient=self.member.email,
            subject="Security", body="Security notice", deduplication_key="security", category="security")
        with patch("operations.worker.quiet_until", return_value=until), patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["accepted"], 1)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs["identifier"], security.pk)

    @override_settings(MAIL_DAILY_LIMIT=0)
    def test_global_mail_budget_defers_without_consuming_a_transport_attempt(self):
        message = self.message()
        with patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["deferred"], 1)
        send.assert_not_called()
        message.refresh_from_db()
        self.assertEqual(message.attempts, 0)
        self.assertEqual(message.status, "queued")

    def test_stale_alerts_are_removed_after_membership_revocation(self):
        UserAlert.objects.create(user=self.member, project=self.project, category="task_due", title="Task",
            body="Detail", target_url="/app/", deduplication_key="alert", target_type="task", target_id=self.task.pk,
            target_revision=self.task.due_at.isoformat())
        remove_stale_alerts()
        self.assertEqual(UserAlert.objects.count(), 1)
        ProjectMembership.objects.filter(pk=self.membership.pk).update(removed_at=timezone.now())
        remove_stale_alerts()
        self.assertFalse(UserAlert.objects.exists())


class ExportWorkerTests(OperationsTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        context = override_settings(MEDIA_ROOT=directory.name)
        context.enable()
        self.addCleanup(context.disable)
        self.media_root = Path(directory.name)

    def job(self):
        return request_export(actor=self.member, project=self.project, export_format="csv",
                              range_start=timezone.now().date() - timedelta(days=1), range_end=timezone.now().date(), defer=True)

    def test_export_worker_rechecks_membership_at_execution_and_download(self):
        job = self.job()
        ProjectMembership.objects.filter(pk=self.membership.pk).update(removed_at=timezone.now())
        with patch("activity.exports._render_csv") as render:
            outcome = process_exports()
        render.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(outcome["failed"], 1)
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.storage_key, "")
        self.assertEqual(list(self.media_root.rglob("*.csv")), [])

    def test_ready_export_becomes_unavailable_after_requester_leaves(self):
        job = self.job()
        self.assertEqual(process_exports()["ready"], 1)
        job.refresh_from_db()
        self.assertTrue(export_file_for_user(user=self.member, job=job).is_file())
        ProjectMembership.objects.filter(pk=self.membership.pk).update(removed_at=timezone.now())
        with self.assertRaises(PermissionDenied):
            export_file_for_user(user=self.member, job=job)

    def test_ready_export_is_private_to_requester_and_expired_download_is_rejected(self):
        job = self.job()
        self.assertEqual(process_exports()["ready"], 1)
        job.refresh_from_db()
        with self.assertRaises(PermissionDenied):
            export_file_for_user(user=self.owner, job=job)
        job.expires_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["expires_at"])
        with self.assertRaises(ValidationError):
            export_file_for_user(user=self.member, job=job)
        job.refresh_from_db()
        self.assertEqual(job.status, "expired")

    def test_inactive_requester_export_fails_without_creating_artifact(self):
        job = self.job()
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        self.assertEqual(process_exports()["failed"], 1)
        job.refresh_from_db()
        self.assertEqual(job.storage_key, "")

    def test_expired_file_cleanup_stays_within_media_root(self):
        job = self.job()
        self.assertEqual(process_exports()["ready"], 1)
        job.refresh_from_db()
        path = self.media_root / job.storage_key
        self.assertTrue(path.is_file())
        job.expires_at = timezone.now() - timedelta(seconds=1)
        job.save(update_fields=["expires_at"])
        self.assertEqual(cleanup_expired_files(), 1)
        self.assertFalse(path.exists())
        job.refresh_from_db()
        self.assertEqual(job.status, "expired")
        self.assertEqual(job.storage_key, "")

    def test_expired_cleanup_does_not_follow_path_traversal(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        outside = Path(directory.name) / "outside.csv"
        outside.write_text("must stay", encoding="utf-8")
        job = self.job()
        job.status, job.storage_key = "ready", str(outside)
        job.completed_at = timezone.now() - timedelta(days=1)
        job.expires_at = timezone.now() - timedelta(seconds=1)
        job.save()
        self.assertEqual(cleanup_expired_files(), 0)
        self.assertEqual(outside.read_text(encoding="utf-8"), "must stay")
