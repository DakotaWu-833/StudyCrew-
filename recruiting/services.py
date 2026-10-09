"""Transactional recruitment, explicit consent, bounded actions and admission."""
from datetime import timedelta
from functools import wraps

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from accounts.models import User
from accounts.policies import require_site_moderator
from activity.services import record_event
from operations.models import OperationAudit
from operations.services import consume_rate
from projects.models import Project, ProjectMembership
from projects.policies import require_project_manager
from .models import Application, Bookmark, Recruitment, RecruitmentReport
from .policies import is_blocked, listing_visible, require_user


def limited(scope, limit=30, seconds=3600):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            actor = kwargs["actor"]
            require_user(User.objects.get(pk=actor.pk))
            if not consume_rate("recruitment-" + scope, str(actor.pk), limit=limit, seconds=seconds):
                raise ValidationError("Too many recruitment actions. Wait before trying again.")
            # Account closure locks the user before project membership. Use the
            # same order and refresh identity after waiting; a request that began
            # before closure must not republish a profile or admit a closed user.
            with transaction.atomic():
                identifiers = {actor.pk}
                if scope == "decision":
                    application = get_object_or_404(Application, pk=kwargs["application_id"])
                    identifiers.add(application.applicant_id)
                locked = {user.pk: user for user in User.objects.select_for_update().filter(pk__in=identifiers).order_by("pk")}
                current = locked[actor.pk]
                require_user(current)
                kwargs["actor"] = current
                return fn(*args, **kwargs)
        return wrapped
    return decorate


def _text(value, field, maximum):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValidationError({field: f"Use 1 to {maximum} characters."})
    return value.strip()


def _tags(value, field, count, length):
    if not isinstance(value, list) or len(value) > count:
        raise ValidationError({field: f"Use at most {count} entries."})
    result, seen = [], set()
    for tag in value:
        tag = _text(tag, field, length)
        if tag.casefold() not in seen:
            result.append(tag); seen.add(tag.casefold())
    return result


def _assign(listing, data):
    for field, maximum in [("title", 120), ("university", 120), ("course", 60), ("term", 80), ("description", 3000)]:
        if field in data: setattr(listing, field, _text(data[field], field, maximum))
    if "skills" in data:
        listing.skills = _tags(data["skills"], "skills", 10, 50)
        # Text matching works identically on SQLite and PostgreSQL, including
        # Unicode skills; JSON's on-disk escaping is deliberately irrelevant.
        listing.skills_search = "\n".join(listing.skills).casefold()
    if "languages" in data: listing.languages = _tags(data["languages"], "languages", 5, 40)
    if "cooperation" in data:
        if data["cooperation"] not in {"online", "campus", "hybrid"}: raise ValidationError({"cooperation": "Choose online, campus or hybrid."})
        listing.cooperation = data["cooperation"]
    if "capacity" in data:
        if isinstance(data["capacity"], bool) or not isinstance(data["capacity"], int) or not 1 <= data["capacity"] <= 20:
            raise ValidationError({"capacity": "Choose 1 to 20 places."})
        listing.capacity = data["capacity"]
    if "expires_at" in data:
        expiry = data["expires_at"]
        if not hasattr(expiry, "tzinfo") or timezone.is_naive(expiry) or not timezone.now() < expiry <= timezone.now() + timedelta(days=90):
            raise ValidationError({"expires_at": "Expiry must be in the future and no more than 90 days away."})
        listing.expires_at = expiry


def _project(actor, project_id):
    project = get_object_or_404(Project.objects.select_for_update(), pk=project_id)
    require_project_manager(actor, project)
    if project.archived_at: raise ValidationError("Archived projects cannot recruit members.")
    return project


def _locked_listing(actor, listing_id, *, owner=False, manager=False):
    # Every mutation locks the project before the card: consistent ordering with
    # all project membership/archival services and admissions from other cards.
    listing = get_object_or_404(Recruitment.objects.select_related("project", "owner"), pk=listing_id)
    project = get_object_or_404(Project.objects.select_for_update(), pk=listing.project_id)
    listing = Recruitment.objects.select_for_update().select_related("owner", "project").get(pk=listing_id)
    listing.project = project
    listing_visible(actor, listing, own=owner)
    if owner and listing.owner_id != actor.pk: raise PermissionDenied("Only the publisher can change this recruitment.")
    if manager: _project(actor, project.pk)
    return listing


def _available(listing):
    if listing.hidden_at or listing.status != "open" or listing.expires_at <= timezone.now():
        raise ValidationError("This recruitment is closed, expired or unavailable.")
    if listing.project.archived_at:
        raise ValidationError("Archived projects cannot recruit members.")
    require_user(User.objects.get(pk=listing.owner_id))
    require_project_manager(listing.owner, listing.project)


@limited("publish", limit=10, seconds=86400)
@transaction.atomic
def publish(*, actor, data):
    # Serialise the per-publisher quota even across distinct projects.
    require_user(User.objects.select_for_update().get(pk=actor.pk))
    if data.get("publish_consent") is not True:
        raise ValidationError({"publish_consent": "Confirm that these card fields and your display name will be visible to signed-in students."})
    required = {"project", "title", "university", "course", "term", "description", "capacity", "expires_at"}
    if required - data.keys(): raise ValidationError("Complete the required recruitment card fields.")
    project = _project(actor, data.get("project"))
    now = timezone.now()
    Recruitment.objects.filter(project=project, status="open", expires_at__lte=now).update(status="closed", updated_at=now)
    if Recruitment.objects.filter(project=project, status="open").exists():
        raise ValidationError("This project already has an open recruitment card.")
    if Recruitment.objects.filter(owner=actor, status="open", expires_at__gt=now).count() >= 5:
        raise ValidationError("Close an existing card before publishing more than five open cards.")
    listing = Recruitment(owner=actor, project=project, published_at=now, consent_at=now)
    _assign(listing, data)
    listing.full_clean(); listing.save()
    return listing


@limited("edit")
@transaction.atomic
def edit(*, actor, listing_id, data):
    listing = _locked_listing(actor, listing_id, owner=True, manager=True)
    if "expected_updated_at" not in data or data["expected_updated_at"] != listing.updated_at:
        raise ValidationError({"expected_updated_at": "This card changed. Refresh before saving."})
    if set(data) - {"title", "university", "course", "term", "description", "skills", "languages", "cooperation", "capacity", "expires_at", "expected_updated_at"}:
        raise ValidationError("Only published card fields can be edited.")
    _assign(listing, data)
    if listing.capacity < listing.applications.filter(status="approved").count():
        raise ValidationError({"capacity": "Capacity cannot be less than already accepted applicants."})
    listing.full_clean(); listing.save()
    return listing


@limited("state")
@transaction.atomic
def change_state(*, actor, listing_id, reopen=False):
    listing = _locked_listing(actor, listing_id, owner=True, manager=reopen)
    if reopen:
        if listing.hidden_at or listing.expires_at <= timezone.now(): raise ValidationError("A hidden or expired card cannot be reopened. Edit its expiry first if needed.")
        if Recruitment.objects.filter(project=listing.project, status="open").exclude(pk=listing.pk).exists():
            raise ValidationError("This project already has an open card.")
        if listing.applications.filter(status="approved").count() >= listing.capacity:
            raise ValidationError("This recruitment has no remaining places.")
        if listing.status != "open" and Recruitment.objects.filter(owner=actor, status="open", expires_at__gt=timezone.now()).count() >= 5:
            raise ValidationError("Close an existing card before opening more than five cards.")
    listing.status = "open" if reopen else "closed"
    listing.save(update_fields=["status", "updated_at"])
    return listing


@limited("apply", limit=10)
@transaction.atomic
def apply(*, actor, listing_id, message):
    listing = _locked_listing(actor, listing_id)
    _available(listing)
    if actor.pk == listing.owner_id: raise ValidationError("You cannot apply to your own recruitment.")
    if ProjectMembership.objects.active().filter(project=listing.project, user=actor).exists():
        raise ValidationError("You are already a member of this team.")
    if listing.applications.filter(status="approved").count() >= listing.capacity:
        raise ValidationError("This recruitment has no remaining places.")
    if listing.applications.filter(applicant=actor).exists():
        raise ValidationError("You already applied to this card. Closed applications cannot be resubmitted.")
    row = Application(recruitment=listing, applicant=actor, message=_text(message, "message", 1500))
    row.full_clean(); row.save()
    return row


@limited("decision", limit=50)
@transaction.atomic
def decide(*, actor, application_id, decision, reason=""):
    application = get_object_or_404(Application, pk=application_id)
    listing = _locked_listing(actor, application.recruitment_id, owner=True, manager=True)
    application = Application.objects.select_for_update().select_related("applicant").get(pk=application_id)
    if decision not in {"approve", "reject"}: raise ValidationError("Choose approve or reject.")
    require_user(application.applicant)
    if is_blocked(actor, application.applicant): raise PermissionDenied("This application is unavailable.")
    final = "approved" if decision == "approve" else "rejected"
    if application.status == final: return application
    if application.status != "pending": raise ValidationError("Only pending applications can be decided.")
    if decision == "approve":
        _available(listing)
        if listing.applications.filter(status="approved").count() >= listing.capacity:
            raise ValidationError("This recruitment has no remaining places.")
        membership = ProjectMembership.objects.select_for_update().filter(project=listing.project, user=application.applicant).first()
        if membership and membership.removed_at is None:
            raise ValidationError("The applicant is already a team member. Close the duplicate application.")
        if membership is None:
            membership = ProjectMembership(project=listing.project, user=application.applicant)
        membership.role = ProjectMembership.Role.MEMBER
        membership.joined_at = timezone.now(); membership.removed_at = None
        membership.full_clean(); membership.save()
        record_event(project=listing.project, actor=actor, event_type="member_joined", target_type="membership", target_id=membership.pk,
                     metadata={"source": "recruitment", "recruitment": str(listing.pk)})
    if not isinstance(reason, str) or len(reason.strip()) > 1000: raise ValidationError({"reason": "Use at most 1000 characters."})
    application.status = final; application.resolved_at = timezone.now(); application.decision_reason = reason.strip()
    application.save(update_fields=["status", "resolved_at", "decision_reason", "updated_at"])
    return application


@limited("withdraw")
@transaction.atomic
def withdraw(*, actor, application_id):
    application = get_object_or_404(Application, pk=application_id, applicant=actor)
    # Withdrawing remains possible after blocking, expiry or project archival.
    Project.objects.select_for_update().get(pk=application.recruitment.project_id)
    application = Application.objects.select_for_update().get(pk=application.pk)
    if application.status == "withdrawn": return application
    if application.status != "pending": raise ValidationError("Only pending applications can be withdrawn. Accepted members use the team's leave workflow.")
    application.status = "withdrawn"; application.resolved_at = timezone.now()
    application.save(update_fields=["status", "resolved_at", "updated_at"])
    return application


@limited("bookmark", limit=100)
@transaction.atomic
def bookmark(*, actor, listing_id, save=True):
    listing = get_object_or_404(Recruitment.objects.select_related("owner", "project"), pk=listing_id)
    if save:
        listing_visible(actor, listing)
        Bookmark.objects.get_or_create(user=actor, recruitment=listing)
    else:
        Bookmark.objects.filter(user=actor, recruitment=listing).delete()


@limited("report", limit=10, seconds=86400)
@transaction.atomic
def report(*, actor, listing_id, reason, details):
    listing = get_object_or_404(Recruitment.objects.select_related("owner", "project"), pk=listing_id)
    listing_visible(actor, listing)
    if listing.owner_id == actor.pk: raise ValidationError("You cannot report your own card.")
    if reason not in {"spam", "harassment", "misleading", "other"}: raise ValidationError({"reason": "Choose a report category."})
    existing = RecruitmentReport.objects.filter(recruitment=listing, reporter=actor, status="open").first()
    if existing: return existing
    details = _text(details, "details", 2000)
    row, _ = RecruitmentReport.objects.get_or_create(recruitment=listing, reporter=actor, status="open", defaults={"reason": reason, "details": details})
    return row


def require_moderator(actor):
    require_user(actor)
    require_site_moderator(actor)


@limited("moderate", limit=100)
@transaction.atomic
def moderate(*, actor, report_id, decision, reason):
    require_moderator(actor)
    report = get_object_or_404(RecruitmentReport.objects.select_related("recruitment"), pk=report_id)
    Project.objects.select_for_update().get(pk=report.recruitment.project_id)
    listing = Recruitment.objects.select_for_update().get(pk=report.recruitment_id)
    report = RecruitmentReport.objects.select_for_update().get(pk=report_id)
    resolution = _text(reason, "reason", 1000)
    if decision not in {"dismiss", "hide", "restore"}: raise ValidationError("Choose dismiss, hide or restore.")
    if listing.owner_id == actor.pk or report.reporter_id == actor.pk: raise PermissionDenied("Another moderator must review your own case.")
    if decision == "hide":
        listing.hidden_at = timezone.now(); listing.hidden_reason = resolution
        listing.applications.filter(status="pending").update(status="cancelled", resolved_at=timezone.now(), updated_at=timezone.now())
    elif decision == "restore":
        listing.hidden_at = None; listing.hidden_reason = ""
    listing.save(update_fields=["hidden_at", "hidden_reason", "updated_at"])
    report.status = "resolved"; report.resolution = resolution; report.reviewed_by = actor
    report.save(update_fields=["status", "resolution", "reviewed_by", "updated_at"])
    OperationAudit.objects.create(actor=actor, action="recruitment_" + decision, target_id=listing.pk,
                                  metadata={"report": str(report.pk), "reason": resolution})
    return report

