from unittest.mock import patch

from django.test import override_settings

from activity.models import ActivityEvent
from operations.models import OutboundMessage, SuppressedAddress, UserBlock
from operations.services import update_preferences
from operations.worker import process_outbound
from projects.models import ProjectInvitation
from projects.workflows import InvitationDeliveryError, create_and_deliver_invitation
from .helpers import OperationsTestCase


@override_settings(ASYNC_REMINDERS=True)
class InvitationQueueTests(OperationsTestCase):
    def invite(self):
        return create_and_deliver_invitation(actor=self.owner, project=self.project,
            invited_email=self.outsider.email, site_url="https://studycrew.example")

    def test_suppressed_invitation_address_rolls_back_invite_instead_of_claiming_queued(self):
        SuppressedAddress.objects.create(email=self.outsider.email, reason="complaint")
        with self.assertRaises(InvitationDeliveryError):
            self.invite()
        self.assertFalse(ProjectInvitation.objects.exists())
        self.assertFalse(OutboundMessage.objects.exists())
        self.assertFalse(ActivityEvent.objects.exists())

    def test_invitation_queued_without_user_reference_rechecks_block_at_delivery_time(self):
        self.invite()
        message = OutboundMessage.objects.get()
        self.assertIsNone(message.user_id)
        UserBlock.objects.create(user=self.outsider, blocked=self.owner)
        with patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["cancelled"], 1)
        send.assert_not_called()

    def test_invitation_recipient_optout_after_enqueue_cancels_delivery(self):
        self.invite()
        update_preferences(self.outsider, {"invitations": False})
        with patch("operations.worker.send_outbound_message") as send:
            self.assertEqual(process_outbound()["cancelled"], 1)
        send.assert_not_called()
