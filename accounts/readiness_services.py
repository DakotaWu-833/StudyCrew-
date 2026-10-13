"""Explicit, transactional account recovery, privacy and device services.

Recovery never signs a user in or bypasses the existing email MFA flow. Security
links are high entropy, expire after 15 minutes, and become invalid when the
password changes. Closing an account preserves shared and immutable evidence.
"""

from __future__ import annotations

import json
import base64
import logging
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.apps import apps
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from accounts.models import (
    AccountDeviceSession, AccountSecurityThrottle, AccountSecurityToken,
    EmailOTPChallenge, PendingEmailChange, Profile, RecoveryEmail, User,
)
from accounts.services import _dummy_password_hash, normalise_email
from django.contrib.auth.hashers import check_password

logger = logging.getLogger(__name__)
TOKEN_TTL = timedelta(minutes=15)
REAUTH_TTL = timedelta(minutes=5)
REAUTH_SESSION_KEY = "accounts.reauthenticated_at"
GENERIC_RECOVERY_MESSAGE = "If the details match an eligible account, we have sent a security link. It expires in 15 minutes."
INVALID_LINK = "This security link is invalid, expired or already used. Request a new link."

PRIVACY_NOTICE = {
    "version": "2026-10-02",
    "visibility": [
        "Your profile name, biography, photo and contributions are visible to members of your private projects. Your sign-in email is not a public profile field.",
        "Project tasks, comments, meeting details, decisions and shared links are accessible to authorised project members.",
        "Project chat is visible to current project members. Time-record notes are private to their author; teams see completed time totals and task estimates.",
        "When you choose offline task copies, selected task details and pending edits are stored on this device for up to 24 hours. They are cleared when you sign out, close your account here, or sign in with another account. Changes sync only after authentication and conflict checks.",
        "Your recovery email and device sessions are private to your account. Authorised operators may access records to provide support or investigate abuse.",
    ],
    "retention": [
        "Before closing your account, transfer ownership or archive every active project you own. Closing immediately disables sign-in, revokes sessions, removes project access and clears editable profile details and your recovery address. Archived projects remain read-only history.",
        "Shared tasks, comments, meeting records, authorship references and immutable activity/audit evidence are retained for team continuity. Historical metadata may still contain identifying details; account closure is not complete erasure.",
        "Security links expire after 15 minutes. Device sessions follow the configured session expiry. Expired security records are removed by the account security cleanup command.",
        "Closing an account removes its chat message text and presence, stops its recurring task schedules, clears time-record notes and cancels running timers. Completed time totals remain in the team's shared history.",
        "Private export files expire according to their export expiry and are removed by the scheduled export cleanup. Backups follow the operator's documented retention schedule and are not edited by an account closure.",
        "For correction or erasure requests involving retained shared evidence or backups, use the support and privacy request service. Requests require an individual review.",
    ],
    "download": "Your download contains your profile and records attributed to you. It excludes passwords, security secrets and other users' private account data. It is not a full copy of your teams' data.",
}


def _digest(scope: str, value: str) -> str:
    return salted_hmac("accounts.readiness", f"{scope}:{value}", algorithm="sha256").hexdigest()


def _account_auth_digest(user: User) -> str:
    # Email changes invalidate older links even when the password is unchanged.
    return _digest("auth-state", f"{user.get_session_auth_hash()}:{user.email}")


def allow_security_action(*, scope: str, keys: list[str], limit: int = 5, minutes: int = 60) -> bool:
    """Count both successful and failed requests, including unknown accounts."""
    now = timezone.now()
    allowed = True
    with transaction.atomic():
        for digest in sorted({_digest(scope, key) for key in keys}):
            row, _ = AccountSecurityThrottle.objects.select_for_update().get_or_create(key_digest=digest)
            if now - row.window_started_at >= timedelta(minutes=minutes):
                row.count, row.window_started_at = 0, now
            if row.count >= limit:
                allowed = False
            else:
                row.count += 1
            row.save(update_fields=("count", "window_started_at"))
    return allowed


def reauthenticate(*, request, password: str) -> None:
    user = User.objects.get(pk=request.user.pk)
    allowed = allow_security_action(scope="reauth", keys=[str(user.pk)], limit=10, minutes=15)
    if not allowed or not user.is_active or not user.check_password(password):
        raise ValidationError({"current_password": "Check your password or wait before trying again."})
    request.session[REAUTH_SESSION_KEY] = timezone.now().isoformat()


def require_recent_verification(request) -> None:
    raw = request.session.get(REAUTH_SESSION_KEY)
    try:
        verified_at = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        raise PermissionDenied("Confirm your current password before this action.") from None
    now = timezone.now()
    if not timezone.is_aware(verified_at) or not now - REAUTH_TTL <= verified_at <= now:
        raise PermissionDenied("Confirm your current password again. Verification lasts five minutes.")


def track_device_session(request, *, force: bool = False) -> None:
    """Keep session secrets on the server; display a bounded device description."""
    from accounts.session_security import is_mfa_verified
    if not hasattr(request, "session") or not request.session.session_key or not is_mfa_verified(request) or not request.user.is_active:
        return
    now = timezone.now()
    tracking = request.session.get("accounts.device_tracking")
    valid_tracking = isinstance(tracking, dict) and tracking.get("session_key") == request.session.session_key
    if not force:
        if not valid_tracking:
            # Existing sessions are enrolled on the security page or after a
            # minute. Ordinary first GETs must not add database query overhead.
            request.session["accounts.device_tracking"] = {"session_key": request.session.session_key, "seen_at": now.timestamp()}
            return
        seen_at = tracking.get("seen_at")
        if isinstance(seen_at, (int, float)) and 0 <= now.timestamp() - seen_at < 60:
            return
    agent = request.META.get("HTTP_USER_AGENT", "Unknown browser")[:120]
    row, created = AccountDeviceSession.objects.get_or_create(
        session_key=request.session.session_key,
        defaults={"user": request.user, "browser": agent, "last_seen_at": now, "expires_at": request.session.get_expiry_date()},
    )
    if not created and row.user_id == request.user.pk:
        AccountDeviceSession.objects.filter(pk=row.pk).update(last_seen_at=now, expires_at=request.session.get_expiry_date())
    request.session["accounts.device_tracking"] = {"session_key": request.session.session_key, "seen_at": now.timestamp()}


def revoke_all_sessions(user: User, *, except_key: str | None = None) -> int:
    """Revoke registered and pre-feature database sessions for this user."""
    keys = set(AccountDeviceSession.objects.filter(user=user).values_list("session_key", flat=True))
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator(chunk_size=200):
        if session.get_decoded().get("_auth_user_id") == str(user.pk):
            keys.add(session.session_key)
    if except_key:
        keys.discard(except_key)
    count, _ = Session.objects.filter(session_key__in=keys).delete()
    AccountDeviceSession.objects.filter(user=user, session_key__in=keys).delete()
    return count


def revoke_device(*, user: User, device_id) -> bool:
    row = AccountDeviceSession.objects.filter(user=user, pk=device_id).first()
    if row is None:
        raise ValidationError({"device_id": "This session is no longer available."})
    Session.objects.filter(session_key=row.session_key).delete()
    row.delete()
    return True


def _deliver(*, recipient: str, subject: str, body: str, user_id) -> bool:
    try:
        return send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False) == 1
    except Exception:
        # Transport exception strings can contain recipient addresses or message
        # contents. Security email errors must never log those values or traces.
        logger.error("Account security email delivery failed for user %s", user_id)
        return False


def _new_link(*, user: User, purpose: str, destination: str, route: str) -> AccountSecurityToken:
    """Caller locks the user. No request Host is used to build security links."""
    now = timezone.now()
    AccountSecurityToken.objects.filter(user=user, purpose=purpose, consumed_at__isnull=True).update(consumed_at=now)
    raw_token = secrets.token_urlsafe(32)
    row = AccountSecurityToken.objects.create(
        user=user, purpose=purpose, token_digest=_digest("token", raw_token),
        auth_digest=_account_auth_digest(user), destination=destination, expires_at=now + TOKEN_TTL,
    )
    origin = getattr(settings, "PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    link = f"{origin}{reverse(route)}?{urlencode({'token': raw_token})}"
    if not _deliver(
        recipient=destination, subject="Your StudyCrew account security link",
        body=(f"Open this StudyCrew security link:\n{link}\n\nIt expires in 15 minutes and can be used once. "
              "You must confirm the action on the page. If you did not request this, ignore this email.\n"
              "Do not forward this message or share the link."), user_id=user.pk,
    ):
        row.consumed_at = now
        row.save(update_fields=("consumed_at",))
        raise ValidationError("The security email could not be sent. Try again later.")
    return row


def _locked_token(raw: str, purpose: str) -> tuple[User, AccountSecurityToken]:
    if not isinstance(raw, str) or not 40 <= len(raw) <= 128:
        raise ValidationError(INVALID_LINK)
    digest = _digest("token", raw)
    candidate = AccountSecurityToken.objects.filter(token_digest=digest, purpose=purpose).first()
    if not candidate:
        raise ValidationError(INVALID_LINK)
    user = User.objects.select_for_update().get(pk=candidate.user_id)
    row = AccountSecurityToken.objects.select_for_update().get(pk=candidate.pk)
    if (not user.is_active or row.consumed_at is not None or row.expires_at <= timezone.now()
            or not constant_time_compare(row.auth_digest, _account_auth_digest(user))):
        raise ValidationError(INVALID_LINK)
    return user, row


def request_password_reset(*, email: str, ip_address: str) -> None:
    email = normalise_email(email)
    if not allow_security_action(scope="password-reset", keys=[f"email:{email}", f"ip:{ip_address}"]):
        return
    with transaction.atomic():
        user = User.objects.select_for_update().filter(email=email, is_active=True, closed_at__isnull=True).first()
        if user is None or user.email_verified_at is None:
            return
        try:
            _new_link(user=user, purpose=AccountSecurityToken.Purpose.PASSWORD_RESET,
                      destination=user.email, route="accounts:password_reset_confirm")
        except ValidationError:
            # Identical public feedback for unknown, disabled, throttled and delivery failures.
            return


def _invalidate_security(user: User) -> None:
    now = timezone.now()
    AccountSecurityToken.objects.filter(user=user, consumed_at__isnull=True).update(consumed_at=now)
    EmailOTPChallenge.objects.filter(user=user, consumed_at__isnull=True).update(consumed_at=now)
    PendingEmailChange.objects.filter(user=user).delete()


@transaction.atomic
def reset_password(*, token: str, new_password: str) -> None:
    user, row = _locked_token(token, AccountSecurityToken.Purpose.PASSWORD_RESET)
    validate_password(new_password, user=user)
    user.set_password(new_password)
    user.save(update_fields=("password", "updated_at"))
    _invalidate_security(user)
    revoke_all_sessions(user)
    transaction.on_commit(lambda: _deliver(recipient=user.email, subject="Your StudyCrew password was reset",
                                           body="Your password was reset and all sessions were signed out. If this was not you, request another reset and contact support.", user_id=user.pk))


def request_recovery_email(*, user: User, email: str) -> None:
    email = normalise_email(email)
    validate_email(email)
    if email == user.email:
        raise ValidationError({"email": "Use a different, personally accessible recovery address."})
    if not allow_security_action(scope="recovery-setup", keys=[str(user.pk)], limit=5):
        raise ValidationError("Too many recovery address requests. Try again later.")
    with transaction.atomic():
        current = User.objects.select_for_update().filter(pk=user.pk, is_active=True).first()
        if current is None:
            raise PermissionDenied("An active account is required.")
        _new_link(user=current, purpose=AccountSecurityToken.Purpose.RECOVERY_EMAIL,
                  destination=email, route="accounts:recovery_email_confirm")


@transaction.atomic
def confirm_recovery_email(*, token: str) -> None:
    user, row = _locked_token(token, AccountSecurityToken.Purpose.RECOVERY_EMAIL)
    if row.destination == user.email:
        raise ValidationError("Choose a recovery address different from your sign-in email.")
    RecoveryEmail.objects.update_or_create(user=user, defaults={"email": row.destination, "verified_at": timezone.now()})
    AccountSecurityToken.objects.filter(user=user, purpose__in=[
        AccountSecurityToken.Purpose.EMAIL_RECOVERY, AccountSecurityToken.Purpose.RECOVERY_NEW_EMAIL,
    ], consumed_at__isnull=True).update(consumed_at=timezone.now())
    row.consumed_at = timezone.now()
    row.save(update_fields=("consumed_at",))
    transaction.on_commit(lambda: _deliver(recipient=user.email, subject="StudyCrew recovery address updated",
                                           body="A verified recovery address was added to your account. Review it in Account security if this was not you.", user_id=user.pk))


def remove_recovery_email(*, user: User) -> None:
    with transaction.atomic():
        current = User.objects.select_for_update().filter(pk=user.pk, is_active=True).first()
        if current is None:
            raise PermissionDenied("An active account is required.")
        RecoveryEmail.objects.filter(user=current).delete()
        AccountSecurityToken.objects.filter(user=current, purpose__in=[
            AccountSecurityToken.Purpose.RECOVERY_EMAIL, AccountSecurityToken.Purpose.EMAIL_RECOVERY,
            AccountSecurityToken.Purpose.RECOVERY_NEW_EMAIL,
        ], consumed_at__isnull=True).update(consumed_at=timezone.now())


def request_email_recovery(*, email: str, password: str, ip_address: str) -> None:
    email = normalise_email(email)
    allowed = allow_security_action(scope="email-recovery", keys=[f"email:{email}", f"ip:{ip_address}"], limit=5)
    if not allowed:
        return
    with transaction.atomic():
        user = User.objects.select_for_update().filter(email=email, is_active=True, closed_at__isnull=True).first()
        valid = user.check_password(password) if user else check_password(password, _dummy_password_hash())
        if not allowed or not valid or user is None:
            return
        recovery = RecoveryEmail.objects.filter(user=user).first()
        if recovery is None:
            return
        try:
            _new_link(user=user, purpose=AccountSecurityToken.Purpose.EMAIL_RECOVERY,
                      destination=recovery.email, route="accounts:email_recovery_new")
        except ValidationError:
            return


@transaction.atomic
def start_recovered_signin_email(*, token: str, new_email: str) -> None:
    user, row = _locked_token(token, AccountSecurityToken.Purpose.EMAIL_RECOVERY)
    recovery = RecoveryEmail.objects.filter(user=user, email=row.destination).first()
    if recovery is None:
        raise ValidationError(INVALID_LINK)
    new_email = normalise_email(new_email)
    validate_email(new_email)
    if new_email == user.email or User.objects.filter(email=new_email).exists():
        raise ValidationError({"new_email": "Choose a different, available sign-in address."})
    _new_link(user=user, purpose=AccountSecurityToken.Purpose.RECOVERY_NEW_EMAIL,
              destination=new_email, route="accounts:email_recovery_confirm")
    row.consumed_at = timezone.now()
    row.save(update_fields=("consumed_at",))


def finish_recovered_signin_email(*, token: str) -> None:
    try:
        with transaction.atomic():
            user, row = _locked_token(token, AccountSecurityToken.Purpose.RECOVERY_NEW_EMAIL)
            old_email = user.email
            user.email, user.email_verified_at = row.destination, timezone.now()
            user.save(update_fields=("email", "email_verified_at", "updated_at"))
            _invalidate_security(user)
            revoke_all_sessions(user)
            transaction.on_commit(lambda: _deliver(recipient=old_email, subject="StudyCrew sign-in address recovered",
                                                   body="Your sign-in address was recovered using your password and verified recovery address. All sessions were signed out. Contact support if this was not you.", user_id=user.pk))
    except IntegrityError:
        raise ValidationError("That sign-in address is no longer available. Start recovery again.") from None


def personal_data_download(user: User) -> bytes:
    """Export attributed records; no token, password, mail payload or device key."""
    if not allow_security_action(scope="personal-export", keys=[str(user.pk)], limit=3):
        raise ValidationError("You can download account data three times per hour. Try again later.")
    profile = Profile.objects.get(user=user)
    recovery = RecoveryEmail.objects.filter(user=user).first()
    payload = {
        "exported_at": timezone.now(), "notice": PRIVACY_NOTICE["download"],
        "account": {"id": user.pk, "email": user.email, "email_verified_at": user.email_verified_at,
                    "created_at": user.created_at, "last_login": user.last_login},
        "profile": {"display_name": profile.display_name, "course_code": profile.course_code,
                    "time_zone": profile.time_zone, "biography": profile.biography,
                    "major": profile.major, "skills": profile.skills,
                    "communication_languages": profile.communication_languages,
                    "collaboration_preference": profile.collaboration_preference,
                    "avatar_url": profile.avatar_url, "avatar_present": bool(profile.avatar)},
        "recovery_email": {"email": recovery.email, "verified_at": recovery.verified_at} if recovery else None,
        "records": {},
    }
    # Include personal records from launch features without exporting operational
    # mail bodies or secrets. Membership's user FK includes historical membership.
    allowed_apps = {"projects", "tasks", "meetings", "activity", "campus", "coordination", "operations"}
    owner_names = {"user", "owner", "recipient", "author", "actor", "requested_by", "reported_by", "created_by", "creator", "added_by", "reviewer", "submitted_by", "applicant", "organiser"}
    forbidden = {"metadata", "storage_key", "token_hash", "token_digest", "code_hash", "password", "auth_digest"}
    from projects.models import Project
    current_projects = Project.objects.for_user(user).values_list("pk", flat=True)
    shared_editable = {"projects.Project": "id", "tasks.Task": "project_id",
        "meetings.Meeting": "project_id", "campus.TaskPlan": "task__project_id",
        "campus.ResourceLink": "project_id", "operations.ProjectPost": "project_id"}
    for model in apps.get_models():
        if model._meta.app_label not in allowed_apps or model._meta.model_name in {"outboundmessage", "outbounddeliveryattempt"}:
            continue
        owned_fields = [field for field in model._meta.concrete_fields
                        if field.name in owner_names and field.is_relation and field.related_model is User]
        if not owned_fields:
            continue
        own_query = Q()
        for field in owned_fields:
            own_query |= Q(**{field.name: user})
        fields = [field.attname for field in model._meta.concrete_fields
                  if field.name not in forbidden and not any(word in field.name.lower() for word in ("password", "secret", "token", "payload"))]
        queryset = model.objects.filter(own_query)
        project_path = shared_editable.get(model._meta.label)
        if project_path:
            # Attribution never grants a former member access to new edits made
            # by the remaining team. Preserve only original identity references.
            allowed = {f"{project_path}__in": current_projects}
            minimal = [field.attname for field in model._meta.concrete_fields
                       if field.primary_key or field in owned_fields or field.name in {"created_at", "updated_at"}]
            payload["records"][model._meta.label] = [*queryset.filter(**allowed).values(*fields),
                *({**row, "content_withheld": True} for row in queryset.exclude(**allowed).values(*minimal))]
        else:
            payload["records"][model._meta.label] = list(queryset.values(*fields))
    from projects.models import ProjectInvitation
    payload["records"]["projects.ProjectInvitation"] = list(ProjectInvitation.objects.filter(
        Q(invited_by=user) | Q(invited_email=user.email),
    ).values("id", "project_id", "invited_by_id", "invited_email", "status", "expires_at", "responded_at", "created_at"))
    for invitation in payload["records"]["projects.ProjectInvitation"]:
        if invitation["invited_email"] != user.email:
            invitation["invited_email"] = "[recipient address withheld]"
    if apps.is_installed("recruiting"):
        from recruiting.readiness import personal_data
        payload["records"]["recruiting.personal"] = personal_data(user)
    if apps.is_installed("documents_store"):
        from documents_store.account_hooks import export_documents
        payload["records"]["documents_store.personal"] = export_documents(user)
    if apps.is_installed("learning_exchange"):
        from learning_exchange.account_hooks import export_learning
        payload["records"]["learning_exchange.personal"] = export_learning(user)
    for package in ("project_chat", "productivity", "offline_sync"):
        if apps.is_installed(package):
            from importlib import import_module
            payload["records"][f"{package}.personal"] = import_module(f"{package}.services").personal_data(user)
    if profile.avatar:
        try:
            with profile.avatar.open("rb") as photo:
                payload["profile"]["avatar_jpeg_base64"] = base64.b64encode(photo.read()).decode("ascii")
        except OSError:
            payload["profile"]["avatar_download_unavailable"] = True
            logger.warning("Avatar unavailable during personal download for user %s", user.pk)
    return json.dumps(payload, cls=DjangoJSONEncoder, indent=2).encode("utf-8")


@transaction.atomic
def close_account(*, user: User, confirmation: str) -> None:
    """Disable access and remove editable identity; preserve PROTECT references."""
    from activity.models import ActivityEvent, Notification
    from activity.services import record_event
    from projects.models import Project, ProjectInvitation, ProjectMembership
    from tasks.models import TaskAssignment

    if confirmation != "CLOSE MY ACCOUNT":
        raise ValidationError({"confirmation": "Type CLOSE MY ACCOUNT to confirm."})
    current = User.objects.select_for_update().filter(pk=user.pk, is_active=True).first()
    if current is None:
        raise PermissionDenied("An active account is required.")
    membership_ids = list(ProjectMembership.objects.filter(user=current, removed_at__isnull=True).values_list("project_id", flat=True))
    if apps.is_installed("project_chat"):
        membership_ids.extend(apps.get_model("project_chat", "ChatMessage").objects.filter(author=current).values_list("project_id", flat=True))
    if apps.is_installed("documents_store"):
        membership_ids.extend(apps.get_model("documents_store", "ProjectDocument").objects.filter(author=current).values_list("project_id", flat=True))
    # Serialise against project membership and ownership services.
    list(Project.objects.select_for_update().filter(pk__in=membership_ids).order_by("id"))
    memberships = list(ProjectMembership.objects.select_for_update().filter(user=current, removed_at__isnull=True).select_related("project"))
    owners = [membership.project.name for membership in memberships
              if membership.role == ProjectMembership.Role.OWNER and membership.project.archived_at is None]
    if owners:
        raise ValidationError({"ownership": "Transfer ownership or archive these active projects before closing your account: " + ", ".join(owners)})
    now = timezone.now()
    for assignment in TaskAssignment.objects.filter(user=current, task__archived_at__isnull=True).exclude(task__status="done").select_related("task", "task__project"):
        record_event(project=assignment.task.project, actor=current, event_type=ActivityEvent.Type.TASK_UNASSIGNED,
                     target_type=ActivityEvent.TargetType.TASK, target_id=assignment.task_id,
                     metadata={"user_id": str(current.pk), "reason": "account_closed"})
        assignment.task.save(update_fields=["updated_at"])
        assignment.delete()
    for membership in memberships:
        membership.removed_at = now
        membership.save(update_fields=("removed_at",))
        record_event(project=membership.project, actor=current, event_type=ActivityEvent.Type.MEMBER_REMOVED,
                     target_type=ActivityEvent.TargetType.MEMBERSHIP, target_id=membership.pk,
                     metadata={"reason": "account_closed"})
    ProjectInvitation.objects.filter(status="pending").filter(Q(invited_email=current.email) | Q(invited_by=current)).update(status="cancelled", responded_at=now)
    Notification.objects.filter(recipient=current).delete()
    if apps.is_installed("coordination"):
        apps.get_model("coordination", "CalendarSubscription").objects.filter(user=current, revoked_at__isnull=True).update(revoked_at=now)
        apps.get_model("coordination", "WeeklyAvailability").objects.filter(user=current).delete()
    if apps.is_installed("operations"):
        apps.get_model("operations", "UserAlert").objects.filter(user=current).delete()
        apps.get_model("operations", "OutboundMessage").objects.filter(user=current, status__in=["queued", "processing"]).update(status="cancelled", failure_reason="Account closed")
    if apps.is_installed("campus"):
        apps.get_model("campus", "JoinRequest").objects.filter(user=current, status="pending").update(status="rejected")
        apps.get_model("campus", "JoinLink").objects.filter(created_by=current, revoked_at__isnull=True).update(revoked_at=now)
    if apps.is_installed("recruiting"):
        from recruiting.readiness import close_account_records
        close_account_records(current, now)
    if apps.is_installed("documents_store"):
        from documents_store.account_hooks import close_documents
        close_documents(current)
    if apps.is_installed("learning_exchange"):
        from learning_exchange.account_hooks import close_learning
        close_learning(current)
    for package in ("project_chat", "productivity", "offline_sync"):
        if apps.is_installed(package):
            from importlib import import_module
            import_module(f"{package}.services").close_user(current)
    profile = Profile.objects.select_for_update().get(user=current)
    old_avatar, storage = profile.avatar.name, profile.avatar.storage
    profile.display_name, profile.course_code, profile.biography = "Closed account", "", ""
    profile.major, profile.skills, profile.communication_languages, profile.collaboration_preference = "", [], [], ""
    profile.avatar_url, profile.avatar, profile.time_zone = "", "", "UTC"
    profile.save()
    if old_avatar:
        def remove_closed_avatar():
            try:
                storage.delete(old_avatar)
            except OSError:
                logger.exception("Closed-account avatar cleanup failed for user %s", current.pk)
        transaction.on_commit(remove_closed_avatar)
    RecoveryEmail.objects.filter(user=current).delete()
    _invalidate_security(current)
    revoke_all_sessions(current)
    current.email = f"closed-{current.pk.hex}@closed.invalid"
    current.email_verified_at, current.closed_at, current.is_active = None, now, False
    current.is_staff, current.is_superuser = False, False
    current.set_unusable_password()
    current.save(update_fields=("email", "email_verified_at", "closed_at", "is_active", "is_staff", "is_superuser", "password", "updated_at"))
    current.groups.clear()
    current.user_permissions.clear()
