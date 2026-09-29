from unittest.mock import Mock, patch

from django.core import mail
from django.test import SimpleTestCase, override_settings

from integrations.reminder_email import (
    ReminderDeliveryError,
    deliver_reminder_emails,
)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ReminderEmailTests(SimpleTestCase):
    def test_each_unique_recipient_gets_an_isolated_plain_text_message(self):
        result = deliver_reminder_emails(
            subject="[StudyCrew] Task reminder",
            message="Open the authorised task link.",
            recipient_emails=(
                "MEMBER@example.com",
                "facilitator@example.com",
                "member@example.com",
            ),
        )

        self.assertEqual(result.recipient_count, 2)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            {tuple(message.to) for message in mail.outbox},
            {("member@example.com",), ("facilitator@example.com",)},
        )
        self.assertTrue(all(not message.cc and not message.bcc for message in mail.outbox))
        self.assertTrue(all(message.content_subtype == "plain" for message in mail.outbox))

    @patch("integrations.reminder_email.get_connection")
    def test_backend_exception_is_replaced_with_safe_delivery_error(self, get_connection):
        connection = Mock()
        connection.send_messages.side_effect = OSError("private SMTP detail")
        get_connection.return_value = connection

        with self.assertRaisesMessage(
            ReminderDeliveryError,
            "The reminder email could not be sent.",
        ):
            deliver_reminder_emails(
                subject="Reminder",
                message="Body",
                recipient_emails=("member@example.com",),
            )

    @patch("integrations.reminder_email.get_connection")
    def test_partial_backend_acceptance_is_a_failure(self, get_connection):
        connection = Mock()
        connection.send_messages.return_value = 1
        get_connection.return_value = connection

        with self.assertRaises(ReminderDeliveryError):
            deliver_reminder_emails(
                subject="Reminder",
                message="Body",
                recipient_emails=("first@example.com", "second@example.com"),
            )

    def test_empty_batch_is_rejected_before_opening_the_backend(self):
        with self.assertRaises(ReminderDeliveryError):
            deliver_reminder_emails(
                subject="Reminder",
                message="Body",
                recipient_emails=(),
            )
