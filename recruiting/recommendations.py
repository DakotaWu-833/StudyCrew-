"""Explainable discovery using the requesting student's own preferences only."""

import unicodedata

from django.core.exceptions import ValidationError
from django.db.models import Exists, F, OuterRef

from accounts.models import User
from campus.models import Course, ProjectCourse
from projects.models import ProjectMembership
from .models import Application, Bookmark
from .policies import require_user
from .selectors import available_query, card_row


CANDIDATE_WINDOW = 200


def normalise(value, *, course=False):
    """Match whole entries across Unicode width, case and spacing variants."""
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return "".join(text.split()) if course else " ".join(text.split())


def _entries(values):
    # JSON-backed optional profile fields may predate current validators.
    return [value.strip() for value in values if isinstance(value, str) and value.strip()] if isinstance(values, list) else []


def preferences(user, overrides):
    profile = getattr(user, "profile", None)
    courses = list(Course.objects.filter(owner=user).values("code", "university"))
    courses.extend(ProjectCourse.objects.filter(
        project__memberships__user=user, project__memberships__removed_at__isnull=True,
        project__archived_at__isnull=True, term__archived_at__isnull=True,
    ).values("course__code", "course__university"))
    courses = [{"code": value.get("code", value.get("course__code")),
                "university": value.get("university", value.get("course__university"))} for value in courses]
    if getattr(profile, "course_code", ""):
        courses.append({"code": profile.course_code, "university": ""})
    if overrides.get("course"):
        courses = [{"code": overrides["course"], "university": overrides.get("university", "")}]
    elif overrides.get("university"):
        # A university alone cannot infer a course match.
        courses = [value for value in courses if normalise(value["university"]) == normalise(overrides["university"])]
    unique = {}
    for value in courses:
        unique[(normalise(value["code"], course=True), normalise(value["university"]))] = value
    skills = [overrides["skill"]] if overrides.get("skill") else _entries(getattr(profile, "skills", []))
    languages = [overrides["language"]] if overrides.get("language") else _entries(getattr(profile, "communication_languages", []))
    cooperation = overrides.get("cooperation") or {"in_person": "campus"}.get(
        getattr(profile, "collaboration_preference", ""), getattr(profile, "collaboration_preference", ""))
    return {"courses": list(unique.values()), "skills": skills, "languages": languages, "cooperation": cooperation,
            "overrides": [name for name, value in overrides.items() if value],
            "missing_fields": [name for name, present in [("course", unique), ("skills", skills), ("languages", languages), ("working style", cooperation)] if not present]}


def match_reasons(listing, basis):
    reasons = []
    for course in basis["courses"]:
        if normalise(course["code"], course=True) == normalise(listing.course, course=True) and (
            not course["university"] or normalise(course["university"]) == normalise(listing.university)
        ):
            reasons.append({"kind": "course", "values": [listing.course], "text": f"Course code matches: {listing.course}. School details are self-reported."})
            break
    for kind, field, label in [("skills", "skills", "Skills in common"), ("languages", "languages", "Communication languages in common")]:
        wanted = {normalise(value) for value in basis[field]}
        found = list(dict.fromkeys(value for value in _entries(getattr(listing, field)) if normalise(value) in wanted))
        if found:
            reasons.append({"kind": kind, "values": found, "text": f"{label}: {', '.join(found)}."})
    style = basis["cooperation"]
    if style and (listing.cooperation == style or (listing.cooperation == "hybrid" and style in {"online", "campus"})):
        label = {"online": "online", "campus": "on-campus", "hybrid": "online and on-campus"}[style]
        reasons.append({"kind": "cooperation", "values": [style], "text": f"The advertised working style accommodates your {label} preference."})
    return reasons


def recommendations(*, user, overrides, page=1):
    require_user(user)
    try:
        number = int(page)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"page": "Choose a positive page number."}) from exc
    if number < 1:
        raise ValidationError({"page": "Choose a positive page number."})
    # Refresh identity and profile: account closure and profile edits must take
    # effect even if this request was handed a previously loaded User object.
    current = User.objects.select_related("profile").get(pk=user.pk)
    require_user(current)
    basis = preferences(current, overrides)
    member = ProjectMembership.objects.active().filter(project_id=OuterRef("project_id"), user=current)
    applied = Application.objects.filter(recruitment_id=OuterRef("pk"), applicant=current)
    query = available_query(current, only_open=True).exclude(owner=current).annotate(
        already_member=Exists(member), already_applied=Exists(applied),
    ).filter(already_member=False, already_applied=False, accepted__lt=F("capacity"))
    eligible_count = query.count()
    candidates = list(query.order_by("-published_at", "-id")[:CANDIDATE_WINDOW])
    matches = []
    for listing in candidates:
        reasons = match_reasons(listing, basis)
        if reasons:
            kinds = {reason["kind"] for reason in reasons}
            matches.append((listing, reasons, tuple(kind in kinds for kind in ["course", "skills", "languages", "cooperation"])))
    # This is a declared relevance order, not a student/team quality score.
    # Python's stable sort preserves the newest-first order for matching ties.
    matches.sort(key=lambda entry: entry[2], reverse=True)
    count = len(matches); pages = max(1, (count + 19) // 20); number = min(number, pages)
    chosen = matches[(number - 1) * 20:number * 20]
    bookmarks = set(Bookmark.objects.filter(user=current, recruitment_id__in=[row.pk for row, _, _ in chosen]).values_list("recruitment_id", flat=True))
    return {"results": [{**card_row(row, current, bookmarks=bookmarks, my_application=False), "match_reasons": reasons} for row, reasons, _ in chosen],
            "count": count, "page": number, "pages": pages, "page_size": 20, "preferences": basis,
            "examined_count": len(candidates), "eligible_count": eligible_count, "candidate_window": CANDIDATE_WINDOW,
            "limited": eligible_count > CANDIDATE_WINDOW,
            "ordering": "Course, then skills, language and working style; newest first for ties."}
