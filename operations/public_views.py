import hashlib
import hmac
import json
import secrets
from datetime import timedelta

from django import forms
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db import DatabaseError, connection
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from accounts.services import client_ip
from .models import ContactRequest, OutboundMessage, SuppressedAddress, WebhookReceipt, WorkerHeartbeat
from .selectors import current_notices
from .services import consume_rate


class ContactForm(forms.Form):
    email = forms.EmailField(max_length=254)
    category = forms.ChoiceField(choices=ContactRequest._meta.get_field("category").choices)
    subject = forms.CharField(max_length=160)
    description = forms.CharField(max_length=4000, widget=forms.Textarea(attrs={"rows": 5}))


@require_http_methods(["GET", "POST"])
def help_page(request):
    form = ContactForm(request.POST or None)
    message = ""
    if request.method == "POST" and form.is_valid():
        if consume_rate("public-support", client_ip(request), limit=5, seconds=3600) and consume_rate("public-support-email", form.cleaned_data["email"].lower(), limit=3, seconds=3600):
            raw = secrets.token_urlsafe(32)
            row = ContactRequest.objects.create(**form.cleaned_data,
                verification_hash=salted_hmac("support.verify", raw, algorithm="sha256").hexdigest(),
                expires_at=timezone.now() + timedelta(hours=24))
            link = f"{settings.PUBLIC_BASE_URL}/help/verify/{row.pk}/{raw}/"
            try:
                send_mail("[StudyCrew] Confirm your support request", f"Confirm this request so our support team can read it:\n{link}\n\nExpires in 24 hours. If you did not request support, ignore this message.", settings.DEFAULT_FROM_EMAIL, [row.email], fail_silently=False)
            except Exception:
                row.delete()
        message = "If we can send to that address, a confirmation link will arrive shortly. Confirm it within 24 hours."
        form = ContactForm()
    return render(request, "operations/help.html", {"form": form, "message": message, "contact_email": settings.SERVICE_CONTACT_EMAIL})


@require_http_methods(["GET", "POST"])
def contact_verify(request, identifier, token):
    digest = salted_hmac("support.verify", token, algorithm="sha256").hexdigest()
    with transaction.atomic():
        row = ContactRequest.objects.select_for_update().filter(pk=identifier, expires_at__gt=timezone.now(), verified_at__isnull=True).first()
        valid = bool(row and secrets.compare_digest(row.verification_hash, digest))
        confirmed = valid and request.method == "POST"
        if confirmed:
            row.verified_at = timezone.now()
            row.verification_hash = ""
            row.save(update_fields=["verified_at", "verification_hash", "updated_at"])
    response = render(request, "operations/contact_verified.html", {"valid": valid, "confirmed": confirmed})
    response["Cache-Control"] = "no-store, private"
    response["Referrer-Policy"] = "no-referrer"
    return response


def privacy_page(request):
    return render(request, "operations/privacy.html", {"mail_retention": settings.MAIL_RETENTION_DAYS})


def status_page(request):
    worker = WorkerHeartbeat.objects.filter(name="delivery").first()
    worker_ok = bool(worker and worker.last_run_at >= timezone.now() - timedelta(minutes=5))
    return render(request, "operations/status.html", {"notices": current_notices(), "worker_ok": worker_ok,
        "maintenance": settings.MAINTENANCE_MODE})


@require_http_methods(["GET", "HEAD"])
def health_page(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        now = timezone.now()
        worker_ok = WorkerHeartbeat.objects.filter(name="delivery", last_run_at__gte=now - timedelta(minutes=5)).exists()
        ready = worker_ok and not settings.MAINTENANCE_MODE
        response = JsonResponse({"status": "ready" if ready else "degraded"}, status=200 if ready else 503)
    except DatabaseError:
        response = JsonResponse({"status": "unavailable"}, status=503)
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
@require_http_methods(["POST"])
def mail_webhook(request):
    """A signed adapter endpoint; never accepts unsigned vendor payloads."""
    secret = settings.MAIL_WEBHOOK_SECRET
    timestamp = request.headers.get("X-StudyCrew-Timestamp", "")
    signature = request.headers.get("X-StudyCrew-Signature", "")
    if not secret or len(request.body) > 8192:
        return JsonResponse({"detail": "Webhook unavailable."}, status=403)
    try:
        instant = int(timestamp)
    except ValueError:
        return JsonResponse({"detail": "Invalid signature."}, status=401)
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + request.body, hashlib.sha256).hexdigest()
    if abs(timezone.now().timestamp() - instant) > 300 or not hmac.compare_digest(expected, signature):
        return JsonResponse({"detail": "Invalid signature."}, status=401)
    try:
        payload = json.loads(request.body)
        identifier = payload["message_id"]
        event = payload["event"]
        if event not in {"delivered", "bounced", "complained"}:
            raise ValueError
        import uuid
        uuid.UUID(str(identifier))
    except (ValueError, TypeError, KeyError):
        return JsonResponse({"detail": "Invalid event."}, status=400)
    with transaction.atomic():
        message = OutboundMessage.objects.select_for_update().filter(pk=identifier).first()
        if not message:
            return JsonResponse({"detail": "Message unavailable."}, status=404)
        if WebhookReceipt.objects.filter(signature=signature).exists():
            return JsonResponse({"detail": "Event already processed."})
        if message.status == "cancelled":
            # Cancellation is a local terminal state, including account
            # closure while SMTP was already in flight. A provider cannot
            # revive it. A verified late failure may still suppress an address
            # if a recorded transport attempt exists.
            if message.attempts and event in {"bounced", "complained"}:
                SuppressedAddress.objects.update_or_create(email=message.recipient.lower(), defaults={"reason": "bounce" if event == "bounced" else "complaint"})
            WebhookReceipt.objects.get_or_create(signature=signature)
            return JsonResponse({"detail": "Event already processed."})
        if message.status == event or message.status in {"bounced", "complained"}:
            # Fresh provider retries are idempotent. A late delivered event must
            # never resurrect a suppressed bounce or complaint.
            WebhookReceipt.objects.get_or_create(signature=signature)
            return JsonResponse({"detail": "Event already processed."})
        # Providers can report delivery while the SMTP connection is returning,
        # or after a timeout/worker interruption. A persisted transport attempt
        # is required for those early/late states; a never-sent queued message
        # is rejected. Verified events settle the uncertainty and stop retries.
        attempted = message.attempts > 0 and message.status in {"processing", "queued", "failed"}
        if message.status not in {"accepted", "delivered"} and not attempted:
            return JsonResponse({"detail": "Message unavailable."}, status=404)
        message.status, message.confirmed_at, message.locked_at, message.failure_reason = event, timezone.now(), None, ""
        message.save(update_fields=["status", "confirmed_at", "locked_at", "failure_reason", "updated_at"])
        WebhookReceipt.objects.get_or_create(signature=signature)
        if event in {"bounced", "complained"}:
            SuppressedAddress.objects.update_or_create(email=message.recipient.lower(), defaults={"reason": "bounce" if event == "bounced" else "complaint"})
    return JsonResponse({"detail": "Event processed."})
