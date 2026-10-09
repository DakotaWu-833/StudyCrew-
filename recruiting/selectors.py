"""Signed-in, consent-only discovery; never serialise private project content."""
from math import ceil
from django.core.exceptions import ValidationError
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from projects.models import Project, ProjectMembership
from .models import Application, Bookmark, Recruitment, RecruitmentReport
from .policies import blocked_ids, listing_visible, require_user
from .services import require_moderator


def page_slice(query, page=1, size=20):
    try: page = int(page)
    except (TypeError, ValueError) as exc: raise ValidationError({"page": "Choose a positive page number."}) from exc
    if page < 1: raise ValidationError({"page": "Choose a positive page number."})
    count = query.count(); pages = max(1, ceil(count / size)); page = min(page, pages)
    return query[(page - 1) * size:page * size], {"count": count, "page": page, "pages": pages, "page_size": size}


def people(user):
    return {"id": user.pk, "display_name": getattr(getattr(user, "profile", None), "display_name", "Student")}


def card_query():
    manager = ProjectMembership.objects.active().filter(project_id=OuterRef("project_id"), user_id=OuterRef("owner_id"), role__in=["owner", "facilitator"])
    return Recruitment.objects.select_related("owner__profile", "project").annotate(
        accepted=Count("applications", filter=Q(applications__status="approved"), distinct=True), has_manager=Exists(manager))


def available_query(user, *, only_open=False):
    query = card_query().filter(owner__is_active=True, owner__closed_at__isnull=True, owner__email_verified_at__isnull=False,
                                project__archived_at__isnull=True, hidden_at__isnull=True, has_manager=True)
    query = query.exclude(owner_id__in=blocked_ids(user))
    if only_open: query = query.filter(status="open", expires_at__gt=timezone.now())
    return query


def effective_status(listing):
    if listing.hidden_at: return "hidden"
    if listing.project.archived_at or not listing.owner.is_active or listing.owner.closed_at or not listing.owner.email_verified_at or not getattr(listing, "has_manager", True): return "unavailable"
    if listing.expires_at <= timezone.now(): return "expired"
    return listing.status


def card_row(listing, user, *, bookmarks=None, my_application=None):
    accepted = getattr(listing, "accepted", None)
    if accepted is None: accepted = listing.applications.filter(status="approved").count()
    owner = listing.owner_id == user.pk
    result = {"id": listing.pk, "title": listing.title, "university": listing.university, "course": listing.course, "term": listing.term,
              "description": listing.description, "skills": listing.skills, "languages": listing.languages, "cooperation": listing.cooperation,
              "capacity": listing.capacity, "remaining": max(0, listing.capacity - accepted), "accepted": accepted,
              "expires_at": listing.expires_at, "status": effective_status(listing), "owner": people(listing.owner),
              "student_status": "self_reported", "published_at": listing.published_at, "updated_at": listing.updated_at,
              "is_owner": owner, "bookmarked": listing.pk in bookmarks if bookmarks is not None else Bookmark.objects.filter(user=user, recruitment=listing).exists()}
    if my_application is None: my_application = listing.applications.filter(applicant=user).first()
    result["my_application"] = application_row(my_application, user, include_card=False) if my_application else None
    if result["my_application"] and result["my_application"].get("joined_project"):
        result["joined_project"] = result["my_application"]["joined_project"]
    if owner:
        result["project"] = listing.project_id
        result["hidden_reason"] = listing.hidden_reason
    return result


def application_row(application, user, *, include_card=True):
    row = {"id": application.pk, "status": application.status, "message": application.message, "reason": application.decision_reason,
           "created_at": application.created_at, "resolved_at": application.resolved_at, "applicant": people(application.applicant)}
    if include_card:
        listing = application.recruitment
        # A personal history may keep the applicant's own message after blocking,
        # but must not republish the other person's card or decision text.
        if listing.owner_id in blocked_ids(user):
            row["listing"] = None; row["reason"] = ""
        else:
            row["listing"] = {"id": listing.pk, "title": listing.title, "status": effective_status(listing)}
    if application.applicant_id == user.pk and application.status == "approved" and ProjectMembership.objects.active().filter(project_id=application.recruitment.project_id, user=user).exists():
        row["joined_project"] = application.recruitment.project_id
    return row


def listings(*, user, params):
    require_user(user)
    query = available_query(user, only_open=True)
    for name in ["q", "university", "course", "skill", "cooperation"]:
        if len(str(params.get(name, ""))) > 120: raise ValidationError({name: "Use at most 120 characters."})
    if params.get("q"):
        value = params["q"].strip()
        query = query.filter(Q(title__icontains=value) | Q(description__icontains=value) | Q(course__icontains=value) | Q(university__icontains=value))
    if params.get("university"): query = query.filter(university__icontains=params["university"].strip())
    if params.get("course"): query = query.filter(course__icontains=params["course"].strip())
    if params.get("skill"): query = query.filter(skills_search__icontains=params["skill"].strip().casefold())
    if params.get("cooperation"):
        if params["cooperation"] not in {"online", "campus", "hybrid"}: raise ValidationError({"cooperation": "Choose online, campus or hybrid."})
        query = query.filter(cooperation=params["cooperation"])
    if params.get("saved") == "true": query = query.filter(bookmarks__user=user)
    rows, meta = page_slice(query, params.get("page", 1))
    rows = list(rows); ids = [r.pk for r in rows]
    bookmarks = set(Bookmark.objects.filter(user=user, recruitment_id__in=ids).values_list("recruitment_id", flat=True))
    applications = {a.recruitment_id: a for a in Application.objects.filter(applicant=user, recruitment_id__in=ids).select_related("applicant__profile", "recruitment__project", "recruitment__owner")}
    return {"results": [card_row(r, user, bookmarks=bookmarks, my_application=applications.get(r.pk, False)) for r in rows], **meta}


def detail(*, user, listing_id):
    require_user(user)
    listing = get_object_or_404(card_query(), pk=listing_id)
    listing_visible(user, listing)
    return card_row(listing, user)


def overview(*, user, params):
    require_user(user)
    projects = Project.objects.active().filter(memberships__user=user, memberships__removed_at__isnull=True, memberships__role__in=["owner", "facilitator"]).order_by("name", "id")
    mine, mine_meta = page_slice(card_query().filter(owner=user), params.get("mine_page", 1))
    applications, app_meta = page_slice(Application.objects.filter(applicant=user).select_related("applicant__profile", "recruitment__project", "recruitment__owner"), params.get("applications_page", 1))
    managed, managed_meta = page_slice(projects, params.get("projects_page", 1), size=100)
    return {"managed_projects": [{"id": p.pk, "name": p.name} for p in managed], "projects_pagination": managed_meta,
            "mine": [card_row(row, user) for row in mine], "mine_pagination": mine_meta,
            "applications": [application_row(row, user) for row in applications], "applications_pagination": app_meta,
            "student_status": "self_reported"}


def applications(*, user, listing_id, page=1):
    require_user(user)
    listing = get_object_or_404(card_query(), pk=listing_id, owner=user)
    rows, meta = page_slice(listing.applications.exclude(applicant_id__in=blocked_ids(user)).select_related("applicant__profile", "recruitment__project", "recruitment__owner"), page)
    return {"results": [application_row(row, user, include_card=False) for row in rows], **meta}


def reports(*, user, page=1):
    require_moderator(user)
    rows, meta = page_slice(RecruitmentReport.objects.select_related("reporter__profile", "recruitment__owner__profile", "recruitment__project").order_by("status", "-created_at", "-id"), page)
    return {"results": [report_row(row) for row in rows], **meta}


def report_row(report):
    listing = report.recruitment
    return {"id": report.pk, "listing": {"id": listing.pk, "title": listing.title, "description": listing.description,
            "university": listing.university, "course": listing.course, "term": listing.term, "owner": people(listing.owner), "hidden_at": listing.hidden_at},
            "reported_by": people(report.reporter), "reason": report.reason, "details": report.details, "status": report.status,
            "resolution": report.resolution, "created_at": report.created_at}

