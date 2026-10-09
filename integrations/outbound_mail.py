"""Single-recipient transport. Acceptance is never called confirmed delivery."""
from django.conf import settings
from django.core.mail import EmailMessage


def send_outbound_message(*, identifier, recipient, subject, body):
    email = EmailMessage(subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL,
                         to=[recipient], headers={"Message-ID": f"<studycrew-{identifier}@{settings.MAIL_MESSAGE_DOMAIN}>"})
    if email.send(fail_silently=False) != 1:
        raise RuntimeError("The mail server did not accept this message.")
