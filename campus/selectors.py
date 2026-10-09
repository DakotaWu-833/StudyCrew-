"""Membership-scoped academic reads and deliberately private self-reported metadata."""

from math import ceil
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import Q, BooleanField
from django.db.models.expressions import RawSQL
from django.utils import timezone

from projects.models import Project, ProjectMembership
from projects.policies import require_project_member
from tasks.models import Task, TaskComment
from .models import (Term, Course, ProjectCourse, Milestone, TaskPlan, ChecklistItem,
    TaskDependency, TeamAgreement, SubmissionPlan, ResourceLink, JoinLink, JoinRequest)
from .policies import project_access
from .services import TEMPLATES


def person(user):
    return {"id": user.id, "display_name": getattr(getattr(user, "profile", None), "display_name", "Team member")}


def term_row(term):
    return {"id": term.id, "university": term.university, "year": term.year, "name": term.name, "archived_at": term.archived_at}


def course_row(course):
    return {"id": course.id, "university": course.university, "code": course.code, "name": course.name}


def course_link_row(link):
    return {"id": link.id, "project": link.project_id, "course": course_row(link.course), "term": term_row(link.term)}


def item_row(item):
    return {"id": item.id, "text": item.text, "checked": item.checked}


def milestone_row(milestone):
    return {"id": milestone.id, "title": milestone.title, "due_at": milestone.due_at, "done": milestone.done}


def resource_row(resource, user):
    membership = require_project_member(user, resource.project)
    return {"id": resource.id, "project": resource.project_id, "project_name": resource.project.name,
            "title": resource.title, "url": resource.url, "description": resource.description,
            "tags": resource.tags, "pinned": resource.pinned, "added_by": person(resource.added_by),
            "can_edit": user.id == resource.added_by_id or membership.role in ("owner", "facilitator"),
            "created_at": resource.created_at}


def task_row(task):
    plan = getattr(task, "academic_plan", None)
    return {"id": task.id, "project": task.project_id, "project_name": task.project.name,
        "title": task.title, "description": task.description, "status": task.status, "priority": task.priority,
        "internal_due_at": task.due_at, "official_due_at": plan.official_due_at if plan else None,
        "acceptance": plan.acceptance if plan else "", "outcome_url": plan.outcome_url if plan else "",
        "parent": plan.parent_id if plan else None, "milestone": plan.milestone_id if plan else None,
        "reviewer": plan.reviewer_id if plan else None, "review_state": plan.review_state if plan else "draft",
        "review_note": plan.review_note if plan else "", "reviewed_at": plan.reviewed_at if plan else None,
        "tags": plan.tags if plan else [], "estimate_hours": str(plan.estimate_hours) if plan and plan.estimate_hours is not None else None,
        "dependencies": [edge.depends_on_id for edge in task.academic_dependencies.all()],
        "checklist": [item_row(item) for item in task.academic_checklist.all()],
        "assignees": [person(user) for user in task.assignees.all()]}


def task_query(queryset):
    return queryset.select_related("project", "academic_plan", "academic_plan__reviewer").prefetch_related(
        "academic_dependencies", "academic_checklist", "assignees__profile")


def page_slice(queryset, page, size):
    try: page = int(page)
    except (ValueError, TypeError) as exc: raise ValidationError({"page": "Choose a positive page number."}) from exc
    if page < 1: raise ValidationError({"page": "Choose a positive page number."})
    total = queryset.count()
    pages = max(1, ceil(total / size))
    page = min(page, pages)
    return queryset[(page - 1) * size:page * size], {"total": total, "page": page, "page_size": size, "pages": pages}


def overview(user):
    projects = Project.objects.for_user(user)
    return {
        "terms": [term_row(t) for t in Term.objects.filter(owner=user)],
        "courses": [course_row(c) for c in Course.objects.filter(owner=user)],
        "links": [course_link_row(link) for link in ProjectCourse.objects.filter(project__in=projects, course__owner=user, term__owner=user).select_related("course", "term")],
        "join_requests": [{"id": r.id, "status": r.status, "created_at": r.created_at,
                           "project": r.project_id if r.status == "approved" else None} for r in JoinRequest.objects.filter(user=user).order_by("-created_at")[:50]],
        "templates": [{"key": key, "name": value["name"], "task_count": len(value["tasks"])} for key, value in TEMPLATES.items()],
    }


def personal_todos(*, user, query="", due="open", page=1):
    tasks = Task.objects.filter(project__in=Project.objects.for_user(user).filter(archived_at=None),
                                archived_at=None, assignments__user=user).distinct()
    if due == "overdue": tasks = tasks.filter(due_at__lt=timezone.now()).exclude(status="done")
    elif due == "open": tasks = tasks.exclude(status="done")
    elif due in {"today", "week"}:
        zone = ZoneInfo(user.profile.time_zone)
        today = timezone.localdate(timezone.now(), zone)
        start = datetime.combine(today, time.min, tzinfo=zone)
        end = datetime.combine(today + timedelta(days=1 if due == "today" else 7), time.min, tzinfo=zone)
        tasks = tasks.filter(due_at__gte=start, due_at__lt=end).exclude(status="done")
    elif due != "all":
        from django.core.exceptions import ValidationError
        raise ValidationError({"due": "Choose open, today, week, overdue or all."})
    if query: tasks = tasks.filter(Q(title__icontains=query[:100]) | Q(description__icontains=query[:100]))
    tasks, metadata = page_slice(task_query(tasks.order_by("due_at", "created_at", "id")), page, 25)
    return {"results": [task_row(task) for task in tasks], **metadata}


def search(*, user, query, page=1):
    from meetings.models import Meeting
    from coordination.models import MeetingRecord
    from operations.models import ProjectPost, PostReply
    query = query.strip()[:100]
    projects = Project.objects.for_user(user)
    queries = {
        "projects": projects.filter(Q(name__icontains=query) | Q(description__icontains=query)).order_by("name", "id"),
        "tasks": task_query(Task.objects.filter(project__in=projects, archived_at=None).filter(Q(title__icontains=query) | Q(description__icontains=query))).order_by("title", "id"),
        "resources": ResourceLink.objects.filter(project__in=projects).select_related("project", "added_by__profile").filter(Q(title__icontains=query) | Q(description__icontains=query) | Q(url__icontains=query)),
        "meetings": Meeting.objects.filter(project__in=projects).filter(Q(title__icontains=query) | Q(agenda__icontains=query)).order_by("-starts_at", "id"),
        "minutes": MeetingRecord.objects.filter(meeting__project__in=projects).select_related("meeting").filter(Q(minutes__icontains=query) | Q(decisions__icontains=query)).order_by("-updated_at", "id"),
        "comments": TaskComment.objects.filter(task__project__in=projects, deleted_at__isnull=True, body__icontains=query).select_related("task").order_by("-created_at", "id"),
        "discussions": ProjectPost.objects.filter(project__in=projects, removed_at__isnull=True).filter(Q(title__icontains=query) | Q(body__icontains=query)),
        "replies": PostReply.objects.filter(post__project__in=projects, post__removed_at__isnull=True, removed_at__isnull=True, body__icontains=query).select_related("post").order_by("-created_at", "id"),
    }
    render = {
        "projects": lambda row: {"id": row.pk, "name": row.name},
        "tasks": task_row, "resources": lambda row: resource_row(row, user),
        "meetings": lambda row: {"id": row.pk, "project": row.project_id, "title": row.title},
        "minutes": lambda row: {"id": row.pk, "project": row.meeting.project_id, "title": row.meeting.title, "excerpt": row.minutes[:200]},
        "comments": lambda row: {"id": row.pk, "project": row.task.project_id, "task": row.task_id, "title": row.task.title, "excerpt": row.body[:200]},
        "discussions": lambda row: {"id": row.pk, "project": row.project_id, "title": row.title},
        "replies": lambda row: {"id": row.pk, "project": row.post.project_id, "title": row.post.title, "excerpt": row.body[:200]},
    }
    requested = int(page) if str(page).isdigit() else 0
    if requested < 1: raise ValidationError({"page": "Choose a positive page number."})
    if not query: queries = {key: queryset.none() for key, queryset in queries.items()}
    totals = {key: queryset.count() for key, queryset in queries.items()}
    pages = max(1, *(ceil(value / 25) for value in totals.values()))
    requested = min(requested, pages)
    result = {key: [render[key](row) for row in queryset[(requested - 1) * 25:requested * 25]] for key, queryset in queries.items()}
    return {**result, "counts": totals, "page": requested, "pages": pages, "total": sum(totals.values())}



def resources(*, user, project_id, query="", tag="", page=1):
    project = project_access(user=user, project_id=project_id)
    queryset = ResourceLink.objects.filter(project=project).select_related("project", "added_by__profile")
    if query: queryset = queryset.filter(Q(title__icontains=query[:100]) | Q(description__icontains=query[:100]) | Q(url__icontains=query[:100]))
    if tag:
        tag = tag.strip().lower()[:30]
        if connection.vendor == "postgresql":
            queryset = queryset.filter(tags__contains=[tag])
        else:
            queryset = queryset.annotate(tag_matches=RawSQL(
                'EXISTS (SELECT 1 FROM json_each("campus_resourcelink"."tags") WHERE value = %s)',
                [tag], output_field=BooleanField())).filter(tag_matches=True)
    queryset, metadata = page_slice(queryset, page, 25)
    return {"results": [resource_row(resource, user) for resource in queryset], **metadata}


def project_plan(*, user, project_id, page=1):
    from operations.services import blocked_since
    project = project_access(user=user, project_id=project_id)
    membership = require_project_member(user, project)
    members = list(ProjectMembership.objects.active().filter(project=project, user__is_active=True).select_related("user__profile"))
    agreement = TeamAgreement.objects.filter(project=project).first()
    submission = SubmissionPlan.objects.filter(project=project).first()
    tasks = Task.objects.filter(project=project, archived_at=None).order_by("created_at", "id")
    task_page, task_pagination = page_slice(task_query(tasks), page, 50)
    return {
        "project": {"id": project.id, "name": project.name, "archived_at": project.archived_at, "role": membership.role},
        "current_user": user.id,
        "members": [{**person(m.user), "role": m.role} for m in members],
        "tasks": [task_row(t) for t in task_page], "task_pagination": task_pagination,
        "task_choices": [{"id": t.id, "title": t.title, "status": t.status} for t in tasks],
        "risks": {
            "unassigned": tasks.exclude(status="done").filter(assignments__isnull=True).count(),
            "overdue": tasks.exclude(status="done").filter(due_at__lt=timezone.now()).count(),
            "blocked": tasks.filter(status="blocked").count(),
            "blocked_tasks": [{"id": task.pk, "title": task.title, "since": blocked_since(task)} for task in tasks.filter(status="blocked")],
            "open_dependencies": TaskDependency.objects.filter(task__project=project, task__archived_at__isnull=True, depends_on__archived_at__isnull=True).exclude(task__status="done").exclude(depends_on__status="done").count(),
        },
        "milestones": [milestone_row(m) for m in Milestone.objects.filter(project=project)],
        "course_links": [course_link_row(link) for link in ProjectCourse.objects.filter(project=project).select_related("course", "term")],
        "agreement": {"body": agreement.body, "revision": agreement.revision,
            "confirmations": [{"user": c.user_id, "revision": c.revision, "confirmed_at": c.confirmed_at} for c in agreement.confirmations.all()]} if agreement else None,
        "submission": {"official_due_at": submission.official_due_at, "internal_due_at": submission.internal_due_at,
            "revision": submission.revision, "items": [item_row(i) for i in submission.items.all()],
            "confirmations": [{"user": c.user_id, "revision": c.revision, "confirmed_at": c.confirmed_at} for c in submission.confirmations.all()],
            "receipt_url": submission.receipt_url, "receipt_reference": submission.receipt_reference,
            "submitted_at": submission.submitted_at, "submitted_by": submission.submitted_by_id} if submission else None,
    }


def join_management(*, user, project_id):
    project = project_access(user=user, project_id=project_id)
    from projects.policies import require_project_owner
    require_project_owner(user, project)
    return {"links": [{"id": link.id, "expires_at": link.expires_at, "max_uses": link.max_uses, "uses": link.uses,
             "revoked_at": link.revoked_at} for link in JoinLink.objects.filter(project=project).order_by("-created_at")[:50]],
        "requests": [{"id": r.id, "user": person(r.user), "status": r.status, "created_at": r.created_at}
                     for r in JoinRequest.objects.filter(project=project, status="pending").select_related("user__profile")]}
