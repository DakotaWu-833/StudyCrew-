"""All private reads and mutations recheck current membership."""
from datetime import timedelta
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from accounts.models import User
from operations.models import OperationAudit, UserBlock
from projects.models import Project, ProjectMembership
from projects.policies import require_project_member
from .models import ChatEvent, ChatMessage, ChatPresence


def member_project(user, project_id, *, lock=False):
    if not user.is_active or user.closed_at:
        raise PermissionDenied("An active account is required.")
    query = Project.objects.select_for_update() if lock else Project.objects
    project = query.filter(pk=project_id).first()
    if project is None:
        raise Http404
    require_project_member(user, project)
    return project


def lock_user(actor):
    user = User.objects.select_for_update().filter(pk=actor.pk, is_active=True, closed_at__isnull=True).first()
    if user is None:
        raise PermissionDenied("An active account is required.")
    return user


def blocked_ids(user):
    rows = UserBlock.objects.filter(Q(user=user) | Q(blocked=user)).values_list("user_id", "blocked_id")
    return {b if a == user.pk else a for a, b in rows}


def serialize_message(message, user, blocked=None, membership=None):
    hidden = message.removed_at is not None or message.author_id in (blocked if blocked is not None else blocked_ids(user))
    if membership is None:
        membership = ProjectMembership.objects.active().filter(project_id=message.project_id, user=user).first()
    return {"id": str(message.pk), "author": {"id": str(message.author_id), "display_name": message.author.profile.display_name},
            "body": "" if hidden else message.body, "created_at": message.created_at, "updated_at": message.updated_at,
            "removed": message.removed_at is not None, "hidden": hidden,
            "can_remove": not hidden and bool(membership) and (message.author_id == user.pk or membership.role in {"owner", "facilitator"})}


@transaction.atomic
def conversation(user, project_id, *, since=None, before=None):
    user = lock_user(user)
    project = member_project(user, project_id, lock=True)
    membership = require_project_member(user, project)
    blocked = blocked_ids(user)
    query = ChatMessage.objects.filter(project=project).select_related("author__profile")
    has_more = False
    cursor = ChatEvent.objects.filter(project=project).order_by("-id").values_list("id", flat=True).first() or 0
    if since is not None:
        events = list(ChatEvent.objects.filter(project=project, id__gt=since).select_related("message__author__profile").order_by("id")[:101])
        has_more = len(events) > 100
        events = events[:100]
        messages = list({event.message_id: event.message for event in events}.values())
        cursor = events[-1].pk if events else cursor
    else:
        if before:
            anchor = query.filter(pk=before).first()
            if anchor is None:
                raise Http404
            query = query.filter(Q(created_at__lt=anchor.created_at) | Q(created_at=anchor.created_at, id__lt=anchor.pk))
        messages = list(query.order_by("-created_at", "-id")[:51])
        has_more = len(messages) > 50
        messages = list(reversed(messages[:50]))
    online = ChatPresence.objects.filter(project=project, last_seen_at__gt=timezone.now() - timedelta(seconds=35),
        user__is_active=True, user__closed_at__isnull=True,
        user__project_memberships__project=project, user__project_memberships__removed_at__isnull=True).exclude(user_id__in=blocked).select_related("user__profile").order_by("user__profile__display_name", "user_id")
    return {"messages": [serialize_message(item, user, blocked, membership) for item in messages], "cursor": cursor,
            "has_more": has_more, "older_than": str(messages[0].pk) if since is None and messages and has_more else None,
            "online": [{"id": str(row.user_id), "display_name": row.user.profile.display_name} for row in online],
            "read_only": bool(project.archived_at), "poll_seconds": 2,
            "visibility_key": ",".join(sorted(str(value) for value in blocked))}


@transaction.atomic
def send_message(actor, project_id, *, body, client_nonce):
    user = lock_user(actor)
    project = member_project(user, project_id, lock=True)
    if project.archived_at:
        raise ValidationError("Archived projects are read-only.")
    existing = ChatMessage.objects.filter(author=user, client_nonce=client_nonce).first()
    if existing:
        if existing.project_id != project.pk or existing.body != body:
            raise ValidationError("This retry identifier was already used for different content.")
        return existing, False
    message = ChatMessage(project=project, author=user, body=body, client_nonce=client_nonce)
    message.full_clean()
    message.save()
    ChatEvent.objects.create(project=project, message=message)
    return message, True


@transaction.atomic
def remove_message(actor, project_id, message_id, *, expected_updated_at, reason):
    user = lock_user(actor)
    project = member_project(user, project_id, lock=True)
    if project.archived_at:
        raise ValidationError("Archived projects are read-only.")
    message = ChatMessage.objects.select_for_update().filter(pk=message_id, project=project).first()
    if message is None:
        raise Http404
    membership = require_project_member(user, project)
    if message.author_id != user.pk and membership.role not in {"owner", "facilitator"}:
        raise PermissionDenied("Only the author or a project manager may remove this message.")
    if message.removed_at:
        return message
    if message.updated_at != expected_updated_at:
        raise ValidationError("This message changed. Refresh before removing it.")
    message.removed_at = timezone.now()
    message.body = ""
    message.save(update_fields=["removed_at", "body", "updated_at"])
    ChatEvent.objects.create(project=project, message=message)
    OperationAudit.objects.create(actor=user, action="chat_message_removed", target_id=message.pk, metadata={"project_id": str(project.pk), "reason": reason})
    return message


@transaction.atomic
def heartbeat(actor, project_id):
    user = lock_user(actor)
    project = member_project(user, project_id, lock=True)
    if project.archived_at:
        return
    ChatPresence.objects.update_or_create(project=project, user=user, defaults={"last_seen_at": timezone.now()})


def personal_data(user):
    active = set(ProjectMembership.objects.active().filter(user=user).values_list("project_id", flat=True))
    return [{"id": str(row.pk), "project_id": str(row.project_id), "body": row.body if row.project_id in active else None,
             "content_withheld": row.project_id not in active, "created_at": row.created_at, "removed_at": row.removed_at}
            for row in ChatMessage.objects.filter(author=user).order_by("created_at")]


def close_user(user):
    ChatPresence.objects.filter(user=user).delete()
    for row in ChatMessage.objects.filter(author=user, removed_at__isnull=True).iterator():
        row.body, row.removed_at = "", timezone.now()
        row.save(update_fields=["body", "removed_at", "updated_at"])
        ChatEvent.objects.create(project_id=row.project_id, message=row)
