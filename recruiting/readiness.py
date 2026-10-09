"""Account privacy hooks. Public recruiting copies are explicitly retired."""
from .models import Application, Bookmark, Recruitment, RecruitmentReport


def personal_data(user):
    # Only authored/owned content; no other applicants or private project data.
    return {"recruitments": list(Recruitment.objects.filter(owner=user).values("id", "title", "university", "course", "term", "description", "skills", "languages", "cooperation", "capacity", "status", "expires_at", "published_at", "consent_at")),
            "applications": list(Application.objects.filter(applicant=user).values("id", "recruitment_id", "message", "status", "created_at", "resolved_at")),
            "bookmarks": list(Bookmark.objects.filter(user=user).values("recruitment_id", "created_at")),
            "reports": list(RecruitmentReport.objects.filter(reporter=user).values("id", "recruitment_id", "reason", "details", "status", "resolution", "created_at"))}


def close_account_records(user, now):
    cards = Recruitment.objects.filter(owner=user)
    Application.objects.filter(recruitment__owner=user, status="pending").update(status="cancelled", resolved_at=now, updated_at=now)
    # Editable market/profile and application text is not immutable team evidence.
    cards.update(status="closed", title="Closed recruitment", university="", course="", term="", description="", skills=[], skills_search="", languages=[], hidden_reason="", updated_at=now)
    Application.objects.filter(recruitment__owner=user).update(decision_reason="", updated_at=now)
    Application.objects.filter(applicant=user, status="pending").update(status="cancelled", resolved_at=now, updated_at=now)
    Application.objects.filter(applicant=user).update(message="", decision_reason="", updated_at=now)
    Bookmark.objects.filter(user=user).delete()

