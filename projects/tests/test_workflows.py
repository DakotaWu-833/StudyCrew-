from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings

from projects.models import ProjectInvitation
from projects.services import create_project
from projects.workflows import InvitationDeliveryError, create_and_deliver_invitation


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class InvitationDeliveryWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(
            email="workflow-owner@example.com",
            password="Strong!Passphrase42",
            display_name="Workflow Owner",
        )
        cls.project = create_project(actor=cls.owner, name="Workflow project")

    def test_invitation_email_contains_the_authenticated_workspace_link(self):
        dispatch = create_and_deliver_invitation(
            actor=self.owner,
            project=self.project,
            invited_email="new-member@example.com",
            site_url="https://studycrew.example.edu/",
        )

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["new-member@example.com"])
        self.assertIn(self.project.name, message.body)
        self.assertIn(
            f"https://studycrew.example.edu/app/invitations/{dispatch.invitation.id}/",
            message.body,
        )
        self.assertNotIn(dispatch.token, message.body)

    @patch("projects.workflows.send_mail", side_effect=OSError("mail unavailable"))
    def test_delivery_failure_rolls_back_the_pending_invitation(self, _send_mail):
        with self.assertRaises(InvitationDeliveryError):
            create_and_deliver_invitation(
                actor=self.owner,
                project=self.project,
                invited_email="retryable@example.com",
                site_url="https://studycrew.example.edu/",
            )

        self.assertFalse(
            ProjectInvitation.objects.filter(invited_email="retryable@example.com").exists()
        )

    @patch("projects.workflows.send_mail", return_value=0)
    def test_zero_delivery_count_also_rolls_back(self, _send_mail):
        with self.assertRaises(InvitationDeliveryError):
            create_and_deliver_invitation(
                actor=self.owner,
                project=self.project,
                invited_email="undelivered@example.com",
                site_url="https://studycrew.example.edu/",
            )
        self.assertFalse(
            ProjectInvitation.objects.filter(invited_email="undelivered@example.com").exists()
        )
