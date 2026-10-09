"""Authorised preference/support writes and durable notification scheduling."""
from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import salted_hmac

from accounts.policies import require_site_moderator
from accounts.models import User
from projects.models import ProjectMembership, ProjectInvitation
from projects.policies import require_project_member
from tasks.models import Task
from meetings.models import Meeting, MeetingAttendance
from .models import (ContactRequest, NotificationPreference, OperationAudit, OutboundMessage, ProjectMute,
                     RateBucket, SupportTicket, SuppressedAddress, TicketReply, UserAlert, UserBlock)


CATEGORY_FIELD = {
    "task_due": "task_reminders", "task_overdue": "task_reminders",
    "meeting_reminder": "meeting_reminders", "task_assignment": "assignments",
    "comment_mention": "mentions", "invitation": "invitations", "meeting_change": "meeting_changes",
}


def require_user(user):
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        raise PermissionDenied("An active account is required.")


def preferences_for(user):
    require_user(user)
    return NotificationPreference.objects.get_or_create(user=user)[0]


def channel_enabled(user, category, project=None, channel="in_app", actor=None):
    if not user.is_active:
        return False
    if actor and UserBlock.objects.filter(user=user, blocked=actor).exists():
        return False
    preference = preferences_for(user)
    if not getattr(preference, channel, False):
        return False
    field = CATEGORY_FIELD.get(category)
    if field and not getattr(preference, field):
        return False
    return not (project and ProjectMute.objects.filter(user=user, project=project, muted=True).exists())


@transaction.atomic
def update_preferences(user, values):
    preference = preferences_for(user)
    for field, value in values.items():
        setattr(preference, field, value)
    if bool(preference.quiet_start) != bool(preference.quiet_end):
        raise ValidationError("Set both quiet-hour times, or clear both.")
    if preference.quiet_start and preference.quiet_start == preference.quiet_end:
        raise ValidationError("Quiet hours must have different start and end times.")
    preference.full_clean()
    preference.save()
    return preference


def quiet_until(user, now=None):
    now = now or timezone.now()
    preference = preferences_for(user)
    if not preference.quiet_start or not preference.quiet_end:
        return now
    local = now.astimezone(ZoneInfo(getattr(user.profile, "time_zone", "UTC")))
    clock = local.time().replace(tzinfo=None)
    start, end = preference.quiet_start, preference.quiet_end
    quiet = start <= clock < end if start < end else (clock >= start or clock < end)
    if not quiet:
        return now
    finish = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if finish <= local:
        finish += timedelta(days=1)
    return finish.astimezone(now.tzinfo)


@transaction.atomic
def consume_rate(scope, identity, *, limit=20, seconds=3600):
    """A persistent fixed window, independent of process-local cache state."""
    now = timezone.now()
    key = salted_hmac("operations.rate", f"{scope}:{identity}", algorithm="sha256").hexdigest()
    row, _ = RateBucket.objects.select_for_update().get_or_create(key=key)
    if row.window_started_at <= now - timedelta(seconds=seconds):
        row.window_started_at, row.count = now, 0
    if row.count >= limit:
        return False
    row.count += 1
    row.save(update_fields=["window_started_at", "count"])
    return True


def enqueue_email(*, recipient, subject, body, key, user=None, project=None,
                  category="service", target_type="", target_id=None, target_revision=""):
    recipient = recipient.strip().lower()
    if SuppressedAddress.objects.filter(email=recipient).exists():
        return None
    if user and (user.email.lower() != recipient or not user.email_verified_at or not user.is_active):
        return None
    if user and category != "security" and not channel_enabled(user, category, project, "email"):
        return None
    message, _ = OutboundMessage.objects.get_or_create(deduplication_key=key, defaults={
        "user": user, "project": project, "recipient": recipient, "subject": subject[:200],
        "body": body[:12000], "category": category, "target_type": target_type,
        "target_id": target_id, "target_revision": target_revision,
        "available_at": quiet_until(user) if user and category != "security" else timezone.now(),
    })
    return message


def message_eligible(message):
    """Recheck membership and current domain state immediately before delivery."""
    if SuppressedAddress.objects.filter(email=message.recipient).exists():
        return False
    user = message.user
    if user and (not user.is_active or not user.email_verified_at or user.email.lower() != message.recipient.lower()):
        return False
    if user and message.category != "security" and not channel_enabled(user, message.category, message.project, "email"):
        return False
    if message.target_type == "digest" and (not user or preferences_for(user).digest == "off"):
        return False
    if message.target_type == "contact":
        return ContactRequest.objects.filter(pk=message.target_id, verified_at__isnull=False,
            email__iexact=message.recipient, updated_at=message.target_revision).exists()
    if message.target_type == "invitation":
        invitation = ProjectInvitation.objects.filter(pk=message.target_id, status="pending", expires_at__gt=timezone.now(), project__archived_at__isnull=True).first()
        if not invitation or invitation.invited_email.lower() != message.recipient.lower() or not invitation.invited_by.is_active:
            return False
        recipient_user = User.objects.filter(email__iexact=message.recipient).first()
        if recipient_user and not channel_enabled(recipient_user, "invitation", invitation.project, "email", actor=invitation.invited_by):
            return False
        return True
    if message.project_id:
        if not user or message.project.archived_at or not ProjectMembership.objects.active().filter(user=user, project_id=message.project_id).exists():
            return False
    if message.target_type in {"post", "post_reply"}:
        return discussion_mention_eligible(message)
    if message.target_type == "task_blocked":
        task = Task.objects.filter(pk=message.target_id, project_id=message.project_id, status="blocked", archived_at__isnull=True, assignees=user).first()
        return bool(task and blocked_since(task).isoformat() == message.target_revision)
    if message.target_type == "event":
        from activity.models import ActivityEvent
        event = ActivityEvent.objects.filter(pk=message.target_id, project_id=message.project_id).select_related("actor").first()
        if not event or UserBlock.objects.filter(user=user, blocked=event.actor).exists():
            return False
        if message.category == "task_assignment":
            return Task.objects.filter(pk=event.target_id, archived_at__isnull=True, assignees=user).exclude(status="done").exists()
    if message.target_type == "task":
        task = Task.objects.filter(pk=message.target_id, project_id=message.project_id, archived_at__isnull=True).exclude(status="done").first()
        return bool(task and user and task.assignees.filter(pk=user.pk).exists() and (task.due_at.isoformat() if task.due_at else "") == message.target_revision)
    if message.target_type in {"task_official", "submission", "milestone", "project_deadline"}:
        from campus.models import TaskPlan, SubmissionPlan, Milestone
        if message.target_type == "task_official":
            plan = TaskPlan.objects.filter(pk=message.target_id, task__project_id=message.project_id,
                task__archived_at__isnull=True, task__assignees=user).exclude(task__status="done").first()
            return bool(plan and plan.official_due_at and plan.official_due_at.isoformat() == message.target_revision)
        if message.target_type == "submission":
            plan = SubmissionPlan.objects.filter(pk=message.target_id, project_id=message.project_id, submitted_at__isnull=True).first()
            field, _, revision = message.target_revision.partition(":")
            due = getattr(plan, field, None) if field in {"internal_due_at", "official_due_at"} else None
            return bool(due and due.isoformat() == revision)
        if message.target_type == "milestone":
            milestone = Milestone.objects.filter(pk=message.target_id, project_id=message.project_id, done=False).first()
            return bool(milestone and milestone.due_at and milestone.due_at.isoformat() == message.target_revision)
        return bool(message.project.due_at and message.project.due_at.isoformat() == message.target_revision)
    if message.target_type == "meeting":
        meeting = Meeting.objects.filter(pk=message.target_id, project_id=message.project_id, cancelled_at__isnull=True, archived_at__isnull=True, starts_at__gt=timezone.now()).first()
        return bool(meeting and meeting.starts_at.isoformat() == message.target_revision and not meeting.attendances.filter(user=user, response="declined").exists())
    return True


def _scheduled_alert(*, user, project, category, title, body, path, key, target_type, target_id, revision):
    if channel_enabled(user, category, project):
        UserAlert.objects.get_or_create(deduplication_key=key, defaults={
            "user": user, "project": project, "category": category, "title": title,
            "body": body[:1000], "target_url": path,
            "target_type": target_type, "target_id": target_id, "target_revision": revision,
        })
    enqueue_email(recipient=user.email, subject=f"[StudyCrew] {title}",
                  body=f"{body}\n\n{settings.PUBLIC_BASE_URL.rstrip('/')}{path}\n\nManage reminders in StudyCrew > Notification settings.",
                  key=f"email:{key}", user=user, project=project, category=category,
                  target_type=target_type, target_id=target_id, target_revision=revision)


def schedule_reminders(now=None):
    now = now or timezone.now()
    created = 0
    tasks = Task.objects.filter(archived_at__isnull=True, project__archived_at__isnull=True,
                                due_at__gte=now - timedelta(days=7), due_at__lte=now + timedelta(hours=24)).exclude(status="done").select_related("project")
    for task in tasks.iterator():
        overdue = task.due_at <= now
        category = "task_overdue" if overdue else "task_due"
        revision = task.due_at.isoformat()
        occurrence = now.date().isoformat() if overdue else revision
        members = User.objects.filter(project_memberships__project=task.project,
                                      project_memberships__removed_at__isnull=True,
                                      task_assignments__task=task, is_active=True, email_verified_at__isnull=False).select_related("profile").distinct()
        for user in members:
            key = f"{category}:{task.pk}:{user.pk}:{revision}:{occurrence}"
            title = f"{'Overdue' if overdue else 'Due soon'}: {task.title}"[:200]
            _scheduled_alert(user=user, project=task.project, category=category, title=title,
                             body=f"{task.title} in {task.project.name} is due {revision}. Update your task or ask your team for help.",
                             path=f"/app/projects/{task.project_id}/tasks/{task.id}/", key=key,
                             target_type="task", target_id=task.pk, revision=revision)
            created += 1
    meetings = Meeting.objects.filter(project__archived_at__isnull=True, archived_at__isnull=True,
                                      cancelled_at__isnull=True, starts_at__gt=now, starts_at__lte=now + timedelta(hours=24)).select_related("project")
    for meeting in meetings.iterator():
        band = "1h" if meeting.starts_at <= now + timedelta(hours=1) else "24h"
        members = User.objects.filter(project_memberships__project=meeting.project,
                                      project_memberships__removed_at__isnull=True,
                                      is_active=True, email_verified_at__isnull=False).exclude(pk__in=MeetingAttendance.objects.filter(meeting=meeting, response="declined").values("user_id")).select_related("profile").distinct()
        for user in members:
            revision = meeting.starts_at.isoformat()
            _scheduled_alert(user=user, project=meeting.project, category="meeting_reminder", title=f"Upcoming: {meeting.title}"[:200],
                             body=f"{meeting.title} in {meeting.project.name} starts {revision}. Location: {meeting.location or 'To be confirmed'}.",
                             path=f"/app/projects/{meeting.project_id}/coordination/", key=f"meeting:{meeting.pk}:{user.pk}:{band}:{revision}",
                             target_type="meeting", target_id=meeting.pk, revision=revision)
            created += 1
    created += schedule_academic_deadlines(now)
    created += schedule_blocked_tasks(now)
    for preference in NotificationPreference.objects.exclude(digest="off").filter(email=True, user__is_active=True, user__email_verified_at__isnull=False).select_related("user", "user__profile"):
        user = preference.user
        local = now.astimezone(ZoneInfo(user.profile.time_zone))
        if local.hour < 8 or (preference.digest == "weekly" and local.weekday() != 0):
            continue
        key = f"digest:{user.pk}:{preference.digest}:{local.date().isoformat()}"
        enqueue_email(recipient=user.email, subject="[StudyCrew] Your study summary", body="Summary is prepared at delivery time.", key=key, user=user, category="service", target_type="digest")
    return created


def discussion_mention_eligible(message):
    from .models import ProjectPost, PostReply
    model = PostReply if message.target_type == "post_reply" else ProjectPost
    source = model.objects.filter(pk=message.target_id, removed_at__isnull=True).select_related("author").first()
    if not source or not source.author.is_active or source.updated_at.isoformat() != message.target_revision:
        return False
    post = source.post if isinstance(source, PostReply) else source
    return bool(not post.removed_at and str(message.user_id) in source.mention_ids
                and not UserBlock.objects.filter(user_id=message.user_id, blocked=source.author).exists())


def blocked_since(task):
    from activity.models import ActivityEvent
    event = ActivityEvent.objects.filter(project_id=task.project_id, target_id=task.pk,
        event_type="task_status_changed", metadata__to="blocked").order_by("-occurred_at", "-id").first()
    return event.occurred_at if event else task.updated_at


def schedule_blocked_tasks(now):
    count = 0
    for task in Task.objects.filter(status="blocked", archived_at__isnull=True, project__archived_at__isnull=True).select_related("project"):
        since = blocked_since(task)
        if since > now - timedelta(hours=72):
            continue
        users = User.objects.filter(task_assignments__task=task, project_memberships__project=task.project,
            project_memberships__removed_at__isnull=True, is_active=True, email_verified_at__isnull=False).select_related("profile").distinct()
        for user in users:
            _scheduled_alert(user=user, project=task.project, category="task_overdue", title=f"Still blocked: {task.title}"[:200],
                body=f"This task has been blocked since {since.isoformat()}. Ask your team for help or update the blocker.",
                path=f"/app/projects/{task.project_id}/tasks/{task.pk}/", key=f"blocked:{task.pk}:{user.pk}:{since.isoformat()}:{now.date().isoformat()}",
                target_type="task_blocked", target_id=task.pk, revision=since.isoformat())
            count += 1
    return count


def schedule_academic_deadlines(now):
    from campus.models import TaskPlan, SubmissionPlan, Milestone
    from projects.models import Project
    window = {"due_at__gte": now - timedelta(days=7), "due_at__lte": now + timedelta(hours=24)}
    targets = []
    for plan in TaskPlan.objects.filter(official_due_at__gte=window["due_at__gte"], official_due_at__lte=window["due_at__lte"],
            task__archived_at__isnull=True, task__project__archived_at__isnull=True).exclude(task__status="done").select_related("task__project"):
        if plan.official_due_at != plan.task.due_at:
            targets.append((plan.task.project, plan.official_due_at, "task_official", plan.pk,
                plan.official_due_at.isoformat(), f"Official deadline: {plan.task.title}",
                f"/app/projects/{plan.task.project_id}/tasks/{plan.task_id}/", plan.task_id))
    for plan in SubmissionPlan.objects.filter(project__archived_at__isnull=True, submitted_at__isnull=True).filter(
            Q(internal_due_at__gte=window["due_at__gte"], internal_due_at__lte=window["due_at__lte"])
            | Q(official_due_at__gte=window["due_at__gte"], official_due_at__lte=window["due_at__lte"])).select_related("project"):
        for field, label in [("internal_due_at", "Team submission"), ("official_due_at", "Official submission")]:
            due = getattr(plan, field)
            if due and window["due_at__gte"] <= due <= window["due_at__lte"]:
                targets.append((plan.project, due, "submission", plan.pk, f"{field}:{due.isoformat()}",
                    f"{label}: {plan.project.name}", f"/app/projects/{plan.project_id}/plan/", None))
    for milestone in Milestone.objects.filter(project__archived_at__isnull=True, done=False, **window).select_related("project"):
        targets.append((milestone.project, milestone.due_at, "milestone", milestone.pk, milestone.due_at.isoformat(),
            f"Milestone: {milestone.title}", f"/app/projects/{milestone.project_id}/plan/", None))
    for project in Project.objects.filter(archived_at__isnull=True, **window):
        targets.append((project, project.due_at, "project_deadline", project.pk, project.due_at.isoformat(),
            f"Project deadline: {project.name}", f"/app/projects/{project.pk}/plan/", None))
    count = 0
    for project, due, kind, identifier, revision, title, path, task_id in targets:
        overdue = due <= now
        category = "task_overdue" if overdue else "task_due"
        occurrence = now.date().isoformat() if overdue else "soon"
        recipients = User.objects.filter(project_memberships__project=project, project_memberships__removed_at__isnull=True,
            is_active=True, email_verified_at__isnull=False).select_related("profile").distinct()
        if task_id:
            recipients = recipients.filter(task_assignments__task_id=task_id)
        for user in recipients:
            _scheduled_alert(user=user, project=project, category=category, title=f"{'Overdue' if overdue else 'Due soon'} · {title}"[:200],
                body=f"{title} is due {due.isoformat()}. Check your team plan and submission readiness.", path=path,
                key=f"{kind}:{identifier}:{user.pk}:{revision}:{occurrence}", target_type=kind, target_id=identifier, revision=revision)
            count += 1
    return count


def digest_body(user):
    projects = ProjectMembership.objects.active().filter(user=user, project__archived_at__isnull=True).values_list("project_id", flat=True)
    tasks = Task.objects.filter(project_id__in=projects, assignees=user, archived_at__isnull=True).exclude(status="done").select_related("project").order_by("due_at")[:30]
    lines = ["Your current tasks:"]
    for task in tasks:
        if ProjectMute.objects.filter(user=user, project=task.project, muted=True).exists():
            continue
        lines.append(f"- {task.title} ({task.project.name}); due {task.due_at.isoformat() if task.due_at else 'not set'}")
    return "\n".join(lines) + f"\n\n{settings.PUBLIC_BASE_URL.rstrip('/')}/app/campus/\nManage summaries in Notification settings."


@transaction.atomic
def create_ticket(user, values):
    require_user(user)
    if not consume_rate("support", str(user.pk), limit=10, seconds=86400):
        raise ValidationError("You have reached today's support-request limit.")
    ticket = SupportTicket(user=user, **values)
    ticket.full_clean()
    ticket.save()
    return ticket


@transaction.atomic
def reply_to_ticket(user, ticket, body):
    require_user(user)
    if ticket.user_id != user.id:
        require_site_moderator(user)
    if not consume_rate("support-reply", str(user.pk), limit=40, seconds=3600):
        raise ValidationError("Please wait before sending another reply.")
    reply = TicketReply(ticket=ticket, author=user, body=body)
    reply.full_clean()
    reply.save()
    if ticket.status == "resolved" and ticket.user_id == user.id:
        ticket.status = "open"
    ticket.save(update_fields=["status", "updated_at"])
    if ticket.user_id != user.id:
        enqueue_email(user=ticket.user, recipient=ticket.user.email, subject="[StudyCrew] A support reply is available",
            body=f"Your support request has a reply. Sign in to read it:\n{settings.PUBLIC_BASE_URL}/app/support/",
            key=f"support-reply:{reply.pk}", category="service")
    return reply


@transaction.atomic
def resolve_ticket(actor, ticket, values):
    require_site_moderator(actor)
    if values.get("status") == "resolved" and not values.get("resolution", ticket.resolution).strip():
        raise ValidationError("Include a resolution before closing this request.")
    for field, value in values.items():
        setattr(ticket, field, value)
    ticket.assigned_to = actor
    ticket.full_clean()
    ticket.save()
    OperationAudit.objects.create(actor=actor, action="support_updated", target_id=ticket.id, metadata={"status": ticket.status})
    return ticket


@transaction.atomic
def respond_to_contact(actor, contact, response):
    require_site_moderator(actor)
    if not contact.verified_at:
        raise ValidationError("Only confirmed requests can receive a response.")
    if not response.strip():
        raise ValidationError("Include a response before resolving this request.")
    contact.response, contact.resolved_at = response, timezone.now()
    contact.full_clean(exclude=["verification_hash"])
    contact.save(update_fields=["response", "resolved_at", "updated_at"])
    queued = enqueue_email(recipient=contact.email, subject="[StudyCrew] Response to your support request",
        body=f"{response}\n\nRequest: {contact.subject}\nContact us again at {settings.PUBLIC_BASE_URL}/help/ if you need more assistance.",
        key=f"contact-reply:{contact.pk}:{contact.updated_at.isoformat()}", category="security",
        target_type="contact", target_id=contact.pk, target_revision=contact.updated_at.isoformat())
    if not queued:
        raise ValidationError("This confirmed address is suppressed after a bounce or complaint. Resolve its delivery issue before sending a reply.")
    OperationAudit.objects.create(actor=actor, action="public_support_resolved", target_id=contact.pk)
    return contact
