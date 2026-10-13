"""Application workflows that coordinate domain writes with external delivery."""

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from projects.services import InvitationDispatch, invite_member


class InvitationDeliveryError(RuntimeError):
    """Raised when an invitation cannot be delivered after a valid request."""


@transaction.atomic
def create_and_deliver_invitation(
    *,
    actor,
    project,
    invited_email: str,
    site_url: str,
) -> InvitationDispatch:
    """Create an invitation and send its authenticated in-app acceptance link.

    Email delivery happens inside the outer transaction so a delivery failure
    cannot leave a pending invitation that the owner is unable to retry.
    """

    dispatch = invite_member(
        actor=actor,
        project=project,
        invited_email=invited_email,
    )
    invitation = dispatch.invitation
    invitation_url = (
        f"{site_url.rstrip('/')}/app/invitations/{invitation.id}/"
    )
    body = (
        f"{actor.profile.display_name} invited you to join {invitation.project.name} on StudyCrew.\n\n"
        f"Sign in or create an account using {invitation.invited_email}, then open:\n{invitation_url}\n\n"
        f"This invitation expires on {invitation.expires_at.date().isoformat()}."
    )
    if settings.ASYNC_REMINDERS:
        from operations.services import enqueue_email
        queued = enqueue_email(recipient=invitation.invited_email, subject="You have been invited to a StudyCrew project",
            body=body, key=f"invitation:{invitation.pk}", project=project,
            category="invitation", target_type="invitation", target_id=invitation.pk)
        if queued is None:
            raise InvitationDeliveryError("The invitation email could not be queued for delivery.")
        return dispatch
    try:
        delivered = send_mail(
            subject="You have been invited to a StudyCrew project",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[invitation.invited_email],
            fail_silently=False,
        )
    except Exception as exc:
        raise InvitationDeliveryError("The invitation email could not be delivered.") from exc
    if delivered != 1:
        raise InvitationDeliveryError("The invitation email could not be delivered.")
    return dispatch
