"""Lease-based DB worker; stale jobs never bypass current membership checks."""
from __future__ import annotations
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from integrations.outbound_mail import send_outbound_message
from activity.models import ExportJob
from .models import ContactRequest, OutboundMessage, RateBucket, UserAlert, WebhookReceipt, WorkerHeartbeat
from .services import consume_rate, digest_body, message_eligible, quiet_until, schedule_reminders


def process_outbound(limit=50):
    now = timezone.now()
    # A process dying after SMTP acceptance leaves an uncertain result. Do not
    # silently resend a stale lease; an operator may retry after investigating.
    OutboundMessage.objects.filter(status="processing", locked_at__lt=now - timedelta(minutes=15)).update(
        status="failed", failure_reason="Delivery outcome uncertain after worker interruption.", locked_at=None)
    outcomes = {"accepted": 0, "cancelled": 0, "failed": 0, "deferred": 0}
    candidates = list(OutboundMessage.objects.filter(status="queued", available_at__lte=now).order_by("available_at", "created_at").values_list("id", flat=True)[:limit])
    for identifier in candidates:
        with transaction.atomic():
            claimed = OutboundMessage.objects.filter(pk=identifier, status="queued").update(status="processing", locked_at=now)
        if not claimed:
            continue
        # Every write belongs to this particular lease. Account closure, a
        # provider callback, or recovery of an expired lease can change the row
        # while SMTP is in progress; an old worker must never restore its state.
        lease = OutboundMessage.objects.filter(pk=identifier, status="processing", locked_at=now)
        message = OutboundMessage.objects.select_related("user__profile", "project").get(pk=identifier)
        if not message_eligible(message):
            if lease.update(status="cancelled", locked_at=None, updated_at=timezone.now()):
                outcomes["cancelled"] += 1
            continue
        ready_at = quiet_until(message.user, now) if message.user and message.category != "security" else now
        if ready_at > now:
            if lease.update(status="queued", available_at=ready_at, locked_at=None, updated_at=timezone.now()):
                outcomes["deferred"] += 1
            continue
        if not consume_rate("mail-global", now.date().isoformat(), limit=settings.MAIL_DAILY_LIMIT, seconds=86400):
            if lease.update(status="queued", available_at=now + timedelta(hours=1), locked_at=None, updated_at=timezone.now()):
                outcomes["deferred"] += 1
            continue
        try:
            body = digest_body(message.user) if message.target_type == "digest" else message.body
        except Exception:
            if lease.update(status="failed", failure_reason="Mail preparation unavailable.", locked_at=None, updated_at=timezone.now()):
                outcomes["failed"] += 1
            continue
        # Persist the attempt immediately before entering transport. Signed
        # callbacks may arrive before SMTP returns, and may only settle a
        # message for which a transport attempt was recorded. Never hold a
        # database row lock across a network call.
        message.attempts += 1
        if not lease.update(attempts=message.attempts, updated_at=timezone.now()):
            continue
        try:
            send_outbound_message(identifier=message.id, recipient=message.recipient, subject=message.subject, body=body)
        except Exception:
            if message.attempts < 4:
                if lease.update(status="queued", available_at=timezone.now() + timedelta(minutes=2 ** message.attempts),
                                failure_reason="Mail transport unavailable.", locked_at=None, updated_at=timezone.now()):
                    outcomes["deferred"] += 1
            else:
                if lease.update(status="failed", failure_reason="Mail transport unavailable.", locked_at=None, updated_at=timezone.now()):
                    outcomes["failed"] += 1
            continue
        # A database failure after SMTP success must leave the lease uncertain,
        # never enter the automatic transport-retry branch above.
        lease.update(status="accepted", accepted_at=timezone.now(), failure_reason="", locked_at=None, updated_at=timezone.now())
        outcomes["accepted"] += 1
    return outcomes


def process_exports(limit=5):
    from activity.exports import generate_export
    outcomes = {"ready": 0, "failed": 0}
    now = timezone.now()
    ExportJob.objects.filter(status="processing", updated_at__lt=now - timedelta(minutes=15)).update(status="failed", error_message="The export worker was interrupted. Please retry.")
    for identifier in list(ExportJob.objects.filter(status="queued").order_by("created_at").values_list("id", flat=True)[:limit]):
        if not ExportJob.objects.filter(pk=identifier, status="queued").update(status="processing", updated_at=now):
            continue
        job = ExportJob.objects.select_related("requested_by", "project").get(pk=identifier)
        generate_export(job)
        outcomes["ready" if job.status == "ready" else "failed"] += 1
    return outcomes


def cleanup_expired_files():
    root = Path(settings.MEDIA_ROOT).resolve()
    count = 0
    for job in ExportJob.objects.filter(expires_at__lte=timezone.now()).exclude(storage_key="").iterator():
        path = (root / job.storage_key).resolve()
        if path.is_relative_to(root) and path.is_file():
            path.unlink()
            count += 1
        job.storage_key, job.status = "", "expired"
        job.save(update_fields=["storage_key", "status", "updated_at"])
    cutoff = timezone.now() - timedelta(days=settings.MAIL_RETENTION_DAYS)
    # Delivery status remains available while unnecessary message content expires.
    OutboundMessage.objects.filter(created_at__lt=cutoff).exclude(status__in=["queued", "processing"]).update(body="", recipient="redacted@invalid.local")
    ContactRequest.objects.filter(verified_at__isnull=True, expires_at__lte=timezone.now()).delete()
    RateBucket.objects.filter(window_started_at__lt=timezone.now() - timedelta(days=8)).delete()
    WebhookReceipt.objects.filter(created_at__lt=cutoff).delete()
    from learning_exchange.models import ImportPreview
    ImportPreview.objects.filter(expires_at__lte=timezone.now()).delete()
    return count


def remove_stale_alerts():
    from tasks.models import Task
    from meetings.models import Meeting
    for alert in UserAlert.objects.filter(read_at__isnull=True).select_related("user", "project").iterator():
        from .services import channel_enabled
        valid = alert.user.is_active and not alert.project.archived_at and alert.project.memberships.filter(user=alert.user, removed_at__isnull=True).exists() and channel_enabled(alert.user, alert.category, alert.project)
        if valid and alert.target_type == "task":
            task = Task.objects.filter(pk=alert.target_id, archived_at__isnull=True).exclude(status="done").first()
            valid = bool(task and task.due_at and task.due_at.isoformat() == alert.target_revision and task.assignees.filter(pk=alert.user_id).exists())
        if valid and alert.target_type == "meeting":
            meeting = Meeting.objects.filter(pk=alert.target_id, cancelled_at__isnull=True, archived_at__isnull=True, starts_at__gt=timezone.now()).first()
            valid = bool(meeting and meeting.starts_at.isoformat() == alert.target_revision and not meeting.attendances.filter(user=alert.user, response="declined").exists())
        if valid and alert.target_type in {"task_official", "submission", "milestone", "project_deadline"}:
            # Reuse the same current-domain-state validation as mail delivery,
            # without letting the email-channel preference hide in-app alerts.
            valid = academic_alert_eligible(alert)
        if valid and alert.target_type in {"post", "post_reply"}:
            from .services import discussion_mention_eligible
            valid = discussion_mention_eligible(alert)
        if valid and alert.target_type == "task_blocked":
            from .services import blocked_since
            task = Task.objects.filter(pk=alert.target_id, project_id=alert.project_id, status="blocked", archived_at__isnull=True, assignees=alert.user).first()
            valid = bool(task and blocked_since(task).isoformat() == alert.target_revision)
        if not valid:
            alert.delete()


def academic_alert_eligible(alert):
    from campus.models import TaskPlan, SubmissionPlan, Milestone
    if alert.target_type == "task_official":
        plan = TaskPlan.objects.filter(pk=alert.target_id, task__project_id=alert.project_id, task__archived_at__isnull=True,
            task__assignees=alert.user).exclude(task__status="done").first()
        return bool(plan and plan.official_due_at and plan.official_due_at.isoformat() == alert.target_revision)
    if alert.target_type == "submission":
        plan = SubmissionPlan.objects.filter(pk=alert.target_id, project_id=alert.project_id, submitted_at__isnull=True).first()
        field, _, revision = alert.target_revision.partition(":")
        due = getattr(plan, field, None) if field in {"internal_due_at", "official_due_at"} else None
        return bool(due and due.isoformat() == revision)
    if alert.target_type == "milestone":
        row = Milestone.objects.filter(pk=alert.target_id, project_id=alert.project_id, done=False).first()
        return bool(row and row.due_at and row.due_at.isoformat() == alert.target_revision)
    return bool(alert.project.due_at and alert.project.due_at.isoformat() == alert.target_revision)


def tick(limit=50):
    from productivity.services import generate_due_recurring_tasks
    from offline_sync.services import cleanup_receipts
    from project_chat.models import ChatPresence
    generated = generate_due_recurring_tasks(limit=limit)
    cleanup_receipts()
    ChatPresence.objects.filter(last_seen_at__lt=timezone.now() - timedelta(minutes=5)).delete()
    reminders = schedule_reminders()
    remove_stale_alerts()
    mail = process_outbound(limit)
    exports = process_exports()
    cleaned = cleanup_expired_files()
    result = {"recurring_tasks_created": generated, "reminder_candidates": reminders, "mail": mail, "exports": exports, "files_cleaned": cleaned}
    WorkerHeartbeat.objects.update_or_create(name="delivery", defaults={"last_run_at": timezone.now(), "detail": result})
    return result
