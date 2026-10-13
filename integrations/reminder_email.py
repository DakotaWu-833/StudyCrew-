"""Small, synchronous adapter for project reminder email delivery.

Every recipient receives a separate message.  This keeps project members'
email addresses out of the To/Cc headers seen by other recipients while still
reusing one backend connection for the small course-team batch.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
import uuid

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone


class ReminderDeliveryError(RuntimeError):
    """Raised when the configured email backend cannot accept the full batch."""


@dataclass(frozen=True, slots=True)
class ReminderDeliveryResult:
    """Observable result returned to the API without exposing recipient data."""

    recipient_count: int
    sent_at: datetime | None
    delivery_status: str = "accepted"


def deliver_reminder_emails(
    *,
    subject: str,
    message: str,
    recipient_emails: Iterable[str],
    project=None,
    target_type: str = "",
    target_id=None,
    target_revision: str = "",
    category: str = "service",
) -> ReminderDeliveryResult:
    """Send one plain-text message per unique recipient using one connection."""

    recipients = tuple(
        dict.fromkeys(
            email.strip().lower()
            for email in recipient_emails
            if isinstance(email, str) and email.strip()
        )
    )
    if not recipients:
        raise ReminderDeliveryError("No reminder recipients were supplied.")

    if getattr(settings, "ASYNC_REMINDERS", False):
        from accounts.models import User
        from operations.services import enqueue_email
        batch = uuid.uuid4()
        queued = 0
        for email in recipients:
            user = User.objects.filter(email__iexact=email).first()
            if not user:
                continue
            result = enqueue_email(recipient=email, subject=subject, body=message, key=f"manual:{batch}:{user.id}",
                                   user=user, project=project, category=category, target_type=target_type,
                                   target_id=target_id, target_revision=target_revision)
            queued += int(result is not None)
        if not queued:
            raise ReminderDeliveryError("No recipients have enabled this reminder.")
        return ReminderDeliveryResult(recipient_count=queued, sent_at=None, delivery_status="queued")

    try:
        connection = get_connection(fail_silently=False)
        messages = [
            EmailMessage(
                subject=subject,
                body=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email],
                connection=connection,
            )
            for email in recipients
        ]
        delivered = connection.send_messages(messages)
    except Exception as exc:
        raise ReminderDeliveryError("The reminder email could not be sent.") from exc
    if delivered != len(messages):
        raise ReminderDeliveryError("The reminder email could not be sent.")
    return ReminderDeliveryResult(
        recipient_count=len(recipients),
        sent_at=timezone.now(),
    )
