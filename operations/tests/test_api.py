from datetime import timedelta
from unittest.mock import Mock, patch

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import HttpResponse
from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

from activity.models import ImmutableRecordError
from operations.middleware import OperationsMiddleware
from operations.models import ContactRequest, OperationAudit, OutboundMessage, SupportTicket, SuppressedAddress, UserAlert, UserBlock
from operations.services import message_eligible, respond_to_contact
from operations.worker import process_outbound
from projects.models import Project, ProjectMembership
from .helpers import OperationsTestCase


class OperationsAPITests(OperationsTestCase):
    def contact(self, *, verified=True):
        return ContactRequest.objects.create(email="contact@example.com", category="privacy", subject="Review personal data",
            description="Please review retained records.", verification_hash="a" * 64,
            expires_at=timezone.now() + timedelta(hours=24), verified_at=timezone.now() if verified else None)

    def test_all_operational_reads_require_login_and_completed_mfa(self):
        paths = ["preferences", "alerts", "deliveries", "support", "blocks", "admin/summary"]
        for path in paths:
            self.assertEqual(self.client.get(f"/api/v1/operations/{path}/").status_code, 401)
        self.signin(mfa=False)
        for path in paths:
            self.assertEqual(self.client.get(f"/api/v1/operations/{path}/").status_code, 401)

    def test_unsafe_api_requests_require_csrf_even_after_mfa(self):
        strict = self.signin(client=Client(enforce_csrf_checks=True))
        response = strict.patch("/api/v1/operations/preferences/", {"email": False}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_preferences_cannot_edit_another_user_or_unknown_account_fields(self):
        self.signin()
        response = self.client.patch("/api/v1/operations/preferences/", {"user": str(self.outsider.pk), "email": False}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        from operations.models import NotificationPreference
        self.assertFalse(NotificationPreference.objects.filter(user=self.outsider).exists())

    def test_mutes_require_current_project_membership(self):
        self.signin(self.outsider)
        response = self.client.post("/api/v1/operations/project-mutes/", {"project": str(self.project.pk), "muted": True}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_ticket_lists_are_private_and_other_users_cannot_reply(self):
        ticket = SupportTicket.objects.create(user=self.member, category="privacy", subject="Private request", description="Private details")
        self.signin(self.outsider)
        response = self.client.get("/api/v1/operations/support/")
        self.assertEqual(response.json()["results"], [])
        self.assertNotContains(response, "Private details")
        response = self.client.post(f"/api/v1/operations/support/{ticket.pk}/replies/", {"body": "Unauthorized reply"}, content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ticket.replies.exists())

    def test_ticket_owner_reply_reopens_a_resolved_request(self):
        ticket = SupportTicket.objects.create(user=self.member, category="help", subject="Question", description="Help please", status="resolved", resolution="Answered")
        self.signin()
        response = self.client.post(f"/api/v1/operations/support/{ticket.pk}/replies/", {"body": "I still need help."}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "open")
        self.assertEqual(ticket.replies.count(), 1)

    def test_delivery_history_is_private_and_contains_no_recipient_or_mail_body(self):
        message = self.message()
        self.signin()
        response = self.client.get("/api/v1/operations/deliveries/")
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertNotContains(response, message.body)
        self.assertNotContains(response, message.recipient)
        self.signin(self.outsider)
        self.assertEqual(self.client.get("/api/v1/operations/deliveries/").json()["results"], [])

    def test_alerts_are_not_visible_to_other_users_or_after_membership_revocation(self):
        alert = UserAlert.objects.create(user=self.member, project=self.project, category="task_due", title="Private alert",
            body="Team information", target_url="/app/", deduplication_key="private-alert")
        self.signin(self.outsider)
        self.assertEqual(self.client.get("/api/v1/operations/alerts/").json()["results"], [])
        self.assertEqual(self.client.patch(f"/api/v1/operations/alerts/{alert.pk}/read/").status_code, 404)
        self.signin()
        ProjectMembership.objects.filter(pk=self.membership.pk).update(removed_at=timezone.now())
        self.assertEqual(self.client.get("/api/v1/operations/alerts/").json()["results"], [])

    def test_existing_block_can_be_cancelled_after_leaving_but_unrelated_user_cannot_be_blocked(self):
        UserBlock.objects.create(user=self.member, blocked=self.owner)
        ProjectMembership.objects.filter(pk=self.membership.pk).update(removed_at=timezone.now())
        self.signin()
        response = self.client.post("/api/v1/operations/blocks/", {"user_id": str(self.owner.pk), "blocked": False}, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserBlock.objects.filter(user=self.member).exists())
        unrelated = self.client.post("/api/v1/operations/blocks/", {"user_id": str(self.outsider.pk), "blocked": True}, content_type="application/json")
        self.assertEqual(unrelated.status_code, 403)

    def test_staff_without_both_permissions_cannot_use_moderation_apis(self):
        self.member.is_staff = True
        self.member.save(update_fields=["is_staff"])
        self.signin()
        for path in ["summary", "support", "contacts", "deliveries"]:
            self.assertEqual(self.client.get(f"/api/v1/operations/admin/{path}/").status_code, 403)

    def test_moderators_see_only_verified_public_contacts_and_can_queue_reply(self):
        verified = self.contact()
        pending = self.contact(verified=False)
        self.signin(self.moderator())
        response = self.client.get("/api/v1/operations/admin/contacts/")
        self.assertEqual([row["id"] for row in response.json()["results"]], [str(verified.pk)])
        denied = self.client.post(f"/api/v1/operations/admin/contacts/{pending.pk}/response/", {"response": "Contact support."}, content_type="application/json")
        self.assertEqual(denied.status_code, 404)
        reply = self.client.post(f"/api/v1/operations/admin/contacts/{verified.pk}/response/", {"response": "We will review retained records."}, content_type="application/json")
        self.assertEqual(reply.status_code, 200)
        verified.refresh_from_db()
        self.assertIsNotNone(verified.resolved_at)
        message = OutboundMessage.objects.get(target_type="contact", target_id=verified.pk)
        self.assertEqual(message.recipient, "contact@example.com")
        self.assertTrue(message_eligible(message))
        with patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["accepted"], 1)
        self.assertEqual(send.call_args.kwargs["recipient"], verified.email)
        self.assertEqual(OperationAudit.objects.filter(action="public_support_resolved").count(), 1)

    def test_suppressed_contact_response_rolls_back_resolution_and_audit(self):
        contact = self.contact()
        SuppressedAddress.objects.create(email=contact.email, reason="complaint")
        self.signin(self.moderator())
        response = self.client.post(f"/api/v1/operations/admin/contacts/{contact.pk}/response/", {"response": "Review response."}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        contact.refresh_from_db()
        self.assertIsNone(contact.resolved_at)
        self.assertEqual(contact.response, "")
        self.assertFalse(OperationAudit.objects.exists())
        self.assertFalse(OutboundMessage.objects.exists())

    def test_superseding_contact_response_cancels_stale_queued_reply(self):
        contact = self.contact()
        moderator = self.moderator()
        respond_to_contact(moderator, contact, "Initial response.")
        first = OutboundMessage.objects.get()
        self.assertTrue(message_eligible(first))
        respond_to_contact(moderator, contact, "Corrected response.")
        self.assertFalse(message_eligible(first))
        self.assertEqual(OutboundMessage.objects.count(), 2)

    def test_uncertain_delivery_retry_requires_explicit_acknowledgement_and_is_audited(self):
        message = self.message(status="failed", failure_reason="Delivery outcome uncertain after worker interruption.")
        self.signin(self.moderator())
        path = f"/api/v1/operations/admin/deliveries/{message.pk}/retry/"
        rejected = self.client.post(path, {"reason": "Inspected transport logs"}, content_type="application/json")
        self.assertEqual(rejected.status_code, 400)
        message.refresh_from_db()
        self.assertEqual(message.status, "failed")
        accepted = self.client.post(path, {"reason": "Inspected transport logs", "acknowledge_uncertain_delivery": True}, content_type="application/json")
        self.assertEqual(accepted.status_code, 200)
        message.refresh_from_db()
        self.assertEqual(message.status, "queued")
        self.assertEqual(OperationAudit.objects.get().action, "mail_retry")

    def test_delivery_pagination_keeps_all_own_rows_reachable_without_leaking_others(self):
        for _ in range(28):
            self.message()
        self.signin()
        first = self.client.get("/api/v1/operations/deliveries/").json()
        second = self.client.get("/api/v1/operations/deliveries/", {"page": 2}).json()
        self.assertEqual(first["total"], 28)
        self.assertEqual(first["pages"], 2)
        self.assertEqual(len(first["results"]), 25)
        self.assertEqual(len(second["results"]), 3)
        ids = {row["id"] for row in first["results"] + second["results"]}
        self.assertEqual(len(ids), 28)

    def test_operational_audit_rows_cannot_be_mutated_or_deleted(self):
        audit = OperationAudit.objects.create(actor=self.owner, action="test")
        with self.assertRaises(ImmutableRecordError):
            OperationAudit.objects.filter(pk=audit.pk).update(action="changed")
        with self.assertRaises(ImmutableRecordError):
            OperationAudit.objects.filter(pk=audit.pk).delete()
        audit.action = "changed"
        with self.assertRaises(ImmutableRecordError):
            audit.save()


class MiddlewareReliabilityTests(OperationsTestCase):
    @override_settings(OPERATIONS_RATE_LIMITS=True)
    def test_rate_limit_failure_rejects_write_without_reaching_domain_view(self):
        downstream = Mock(return_value=HttpResponse("should not run"))
        request = RequestFactory().post("/api/v1/projects/", {"name": "Team"})
        request.user = self.member
        with patch("operations.middleware.consume_rate", side_effect=DatabaseError("private database detail")):
            response = OperationsMiddleware(downstream)(request)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private database detail", response.content.decode())
        downstream.assert_not_called()

    @override_settings(OPERATIONS_RATE_LIMITS=True)
    def test_throttled_write_has_retry_after_without_mutation(self):
        downstream = Mock(return_value=HttpResponse("should not run"))
        request = RequestFactory().post("/api/v1/projects/", {})
        request.user = self.member
        with patch("operations.middleware.consume_rate", return_value=False):
            response = OperationsMiddleware(downstream)(request)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Retry-After"], "60")
        downstream.assert_not_called()

    @override_settings(MAINTENANCE_MODE=True)
    def test_maintenance_pauses_collaboration_writes_and_preserves_account_and_support_access(self):
        middleware = OperationsMiddleware(lambda request: HttpResponse("allowed"))
        factory = RequestFactory()
        blocked = factory.post("/api/v1/projects/", {})
        blocked.user = self.member
        self.assertEqual(middleware(blocked).status_code, 503)
        for path in ("/api/v1/account/reauthenticate/", "/api/v1/operations/support/"):
            request = factory.post(path, {})
            request.user = self.member
            self.assertEqual(middleware(request).status_code, 200)
