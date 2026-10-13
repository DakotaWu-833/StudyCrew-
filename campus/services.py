"""Validated, transactional university workflow use cases."""

from collections import defaultdict
from datetime import timedelta
import hashlib
import ipaddress
import secrets
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from activity.services import record_event
from projects.models import Project, ProjectMembership
from projects.services import create_project, transfer_ownership
from projects.policies import require_project_member, require_project_owner, require_project_manager
from tasks.models import Task
from tasks.services import create_task, update_task, replace_assignees

from .models import (Term, Course, ProjectCourse, Milestone, TaskPlan, TaskDependency,
    ChecklistItem, TeamAgreement, AgreementConfirmation, ResourceLink, SubmissionPlan,
    SubmissionItem, SubmissionConfirmation, JoinLink, JoinRequest, JoinAttempt)
from .policies import project_access, own_record, resource_change


def safe_url(value, *, optional=False):
    value = str(value or "").strip()
    if not value and optional:
        return ""
    if len(value) > 2048 or any(ord(c) < 33 for c in value):
        raise ValidationError({"url": "Enter a public HTTP or HTTPS link without spaces."})
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        _ = parsed.port
    except ValueError as exc:
        raise ValidationError({"url": "Enter a valid public HTTP or HTTPS link."}) from exc
    if parsed.scheme not in ("https", "http") or not hostname or parsed.username or parsed.password:
        raise ValidationError({"url": "Only public HTTP or HTTPS links without credentials are allowed."})
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")) or "." not in hostname:
        raise ValidationError({"url": "Local and private network links are not allowed."})
    try:
        if not ipaddress.ip_address(hostname).is_global:
            raise ValidationError({"url": "Private network links are not allowed."})
    except ValueError:
        pass
    return value


def _text(value, field, maximum, *, minimum=1):
    value = str(value or "").strip()
    if not minimum <= len(value) <= maximum:
        raise ValidationError({field: f"Use {minimum} to {maximum} characters."})
    return value


def _dates(internal, official):
    if internal and official and internal > official:
        raise ValidationError({"internal_due_at": "The internal deadline must be at or before the official deadline."})


def _audit(project, actor, action, **metadata):
    record_event(project=project, actor=actor, event_type="project_updated", target_type="project",
                 target_id=project.id, metadata={"campus_action": action, **metadata})


def _locked_project(user, project_id, *, manager=False):
    from accounts.models import User
    current = User.objects.select_for_update().get(pk=user.pk)
    if not current.is_active or current.closed_at:
        raise PermissionDenied("An active account is required.")
    user = current
    project = project_access(user=user, project_id=project_id, write=True, manager=manager)
    return Project.objects.select_for_update().get(pk=project.pk)


@transaction.atomic
def create_term(*, actor, university, year, name):
    if not 2000 <= year <= 2100:
        raise ValidationError({"year": "Choose a year from 2000 to 2100."})
    term = Term(owner=actor, university=_text(university, "university", 120), year=year, name=_text(name, "name", 80))
    term.full_clean(); term.save()
    return term


@transaction.atomic
def create_course(*, actor, university, code, name):
    course = Course(owner=actor, university=_text(university, "university", 120),
                    code=_text(code, "code", 30).upper(), name=_text(name, "name", 120))
    course.full_clean(); course.save()
    return course


@transaction.atomic
def link_course(*, actor, project_id, course_id, term_id):
    project = _locked_project(actor, project_id, manager=True)
    course = own_record(user=actor, model=Course, pk=course_id)
    term = own_record(user=actor, model=Term, pk=term_id, writable=True)
    if course.university.casefold() != term.university.casefold():
        raise ValidationError("Course and term must belong to the same self-reported university.")
    link, created = ProjectCourse.objects.get_or_create(project=project, course=course, term=term)
    if created:
        _audit(project, actor, "course_linked")
    return link


@transaction.atomic
def unlink_course(*, actor, project_id, link_id):
    project = _locked_project(actor, project_id, manager=True)
    get_object_or_404(ProjectCourse, pk=link_id, project=project).delete()
    _audit(project, actor, "course_unlinked")


@transaction.atomic
def archive_term(*, actor, term_id):
    term = own_record(user=actor, model=Term, pk=term_id)
    term = Term.objects.select_for_update().get(pk=term.pk)
    if not term.archived_at:
        term.archived_at = timezone.now(); term.save(update_fields=("archived_at", "updated_at"))
    return term


@transaction.atomic
def save_milestone(*, actor, project_id, data, milestone_id=None):
    project = _locked_project(actor, project_id, manager=True)
    milestone = get_object_or_404(Milestone, pk=milestone_id, project=project) if milestone_id else Milestone(project=project)
    milestone.title = _text(data.get("title", milestone.title), "title", 120)
    if "due_at" in data: milestone.due_at = data["due_at"]
    if "done" in data: milestone.done = data["done"]
    milestone.full_clean(); milestone.save()
    _audit(project, actor, "milestone_saved")
    return milestone


def _check_cycles(edges):
    graph = defaultdict(list)
    for source, target in edges: graph[str(source)].append(str(target))
    state = {}
    for root in tuple(graph):
        stack = [(root, False)]
        while stack:
            node, exiting = stack.pop()
            if exiting:
                state[node] = 2
                continue
            if state.get(node) == 1:
                raise ValidationError({"dependencies": "The task relationships would create a cycle."})
            if state.get(node) == 2:
                continue
            state[node] = 1
            stack.append((node, True))
            stack.extend((child, False) for child in graph[node])


def validate_task_completion(task):
    """Called before the existing transition service changes task state."""
    if ChecklistItem.objects.filter(task=task, checked=False).exists():
        raise ValidationError("Complete this task's checklist before marking it done.")
    if TaskDependency.objects.filter(task=task).exclude(depends_on__status="done").exists():
        raise ValidationError("Complete prerequisite tasks before marking this task done.")
    if TaskPlan.objects.filter(parent=task, task__archived_at__isnull=True).exclude(task__status="done").exists():
        raise ValidationError("Complete child tasks before marking their parent done.")
    plan = TaskPlan.objects.filter(task=task).first()
    if plan and plan.reviewer_id and plan.review_state != "approved":
        raise ValidationError("The nominated reviewer must approve the deliverable before completion.")


@transaction.atomic
def create_subtask(*, actor, project_id, title, parent):
    project = _locked_project(actor, project_id)
    parent_task = get_object_or_404(Task, pk=parent, project=project, archived_at__isnull=True)
    if parent_task.status == "done": raise ValidationError("Reopen the parent task before adding a subtask.")
    task = create_task(project=project, actor=actor, data={"title": title})
    TaskPlan.objects.create(task=task, parent=parent_task)
    return task


@transaction.atomic
def save_task_plan(*, actor, project_id, task_id, data):
    project = _locked_project(actor, project_id)
    task = get_object_or_404(Task, pk=task_id, project=project, archived_at__isnull=True)
    if task.status == "done": raise ValidationError("Reopen the task before changing its plan.")
    plan, _ = TaskPlan.objects.get_or_create(task=task)
    if "parent" in data:
        parent = get_object_or_404(Task, pk=data["parent"], project=project, archived_at__isnull=True) if data["parent"] else None
        edges = list(TaskPlan.objects.filter(task__project=project).exclude(task=task).exclude(parent=None).values_list("task_id", "parent_id"))
        if parent: edges.append((task.id, parent.id))
        _check_cycles(edges); plan.parent = parent
    if "milestone" in data:
        plan.milestone = get_object_or_404(Milestone, pk=data["milestone"], project=project) if data["milestone"] else None
    if "reviewer" in data:
        membership = get_object_or_404(ProjectMembership.objects.active(), project=project, user_id=data["reviewer"], user__is_active=True) if data["reviewer"] else None
        plan.reviewer = membership.user if membership else None
    if "acceptance" in data: plan.acceptance = _text(data["acceptance"], "acceptance", 4000, minimum=0)
    if "tags" in data:
        if not isinstance(data["tags"], list) or len(data["tags"]) > 10: raise ValidationError({"tags": "Use up to ten tags."})
        plan.tags = sorted(set(_text(t, "tags", 30).lower() for t in data["tags"]))
    if "estimate_hours" in data: plan.estimate_hours = data["estimate_hours"]
    if "official_due_at" in data: plan.official_due_at = data["official_due_at"]
    if "outcome_url" in data: plan.outcome_url = safe_url(data["outcome_url"], optional=True)
    internal = data.get("internal_due_at", task.due_at)
    _dates(internal, plan.official_due_at)
    if "dependencies" in data:
        ids = set(data["dependencies"])
        eligible = set(Task.objects.filter(project=project, pk__in=ids, archived_at__isnull=True).values_list("id", flat=True))
        if eligible != ids: raise ValidationError({"dependencies": "Every prerequisite must be a current task in this project."})
        edges = list(TaskDependency.objects.filter(task__project=project).exclude(task=task).values_list("task_id", "depends_on_id"))
        edges.extend((task.id, dependency) for dependency in ids)
        _check_cycles(edges)
        TaskDependency.objects.filter(task=task).delete()
        TaskDependency.objects.bulk_create([TaskDependency(task=task, depends_on_id=pk) for pk in ids])
    plan.review_state = "draft"; plan.review_note = ""; plan.reviewed_at = None
    plan.full_clean(); plan.save()
    if "internal_due_at" in data: update_task(task=task, actor=actor, data={"due_at": internal})
    _audit(project, actor, "task_plan_saved", task_id=str(task.id))
    return plan


@transaction.atomic
def copy_task(*, actor, project_id, task_id, title, reuse_dependencies=False):
    project = _locked_project(actor, project_id)
    original = get_object_or_404(Task, pk=task_id, project=project, archived_at__isnull=True)
    task = create_task(project=project, actor=actor, data={"title": _text(title, "title", 120, minimum=3),
        "description": original.description, "priority": original.priority})
    previous = TaskPlan.objects.filter(task=original).first()
    if previous:
        TaskPlan.objects.create(task=task, acceptance=previous.acceptance, tags=previous.tags,
            estimate_hours=previous.estimate_hours, milestone=previous.milestone)
    ChecklistItem.objects.bulk_create([ChecklistItem(task=task, text=item.text) for item in original.academic_checklist.all()])
    if reuse_dependencies:
        TaskDependency.objects.bulk_create([TaskDependency(task=task, depends_on_id=edge.depends_on_id)
            for edge in original.academic_dependencies.filter(depends_on__archived_at__isnull=True)])
    _audit(project, actor, "task_copied", source_task=str(original.id), task_id=str(task.id), reused_dependencies=bool(reuse_dependencies))
    return task


@transaction.atomic
def bulk_update_tasks(*, actor, project_id, task_ids, data):
    project = _locked_project(actor, project_id)
    if not task_ids or len(task_ids) > 50: raise ValidationError("Choose one to fifty current tasks.")
    if not any(field in data for field in ("assignees", "priority", "internal_due_at")): raise ValidationError("Choose a field to update.")
    ids = set(task_ids)
    tasks = list(Task.objects.select_for_update().filter(project=project, id__in=ids, archived_at__isnull=True))
    if {task.id for task in tasks} != ids: raise ValidationError("Every selected task must be current and in this project.")
    if "assignees" in data:
        eligible = set(ProjectMembership.objects.active().filter(project=project, user__is_active=True).values_list("user_id", flat=True))
        if not set(data["assignees"]).issubset(eligible): raise ValidationError("Every assignee must be an active current member.")
    for task in tasks:
        if task.status == "done": raise ValidationError("Reopen completed tasks before using bulk changes.")
        changes = {field: data[field] for field in ("priority",) if field in data}
        if "internal_due_at" in data:
            plan = TaskPlan.objects.filter(task=task).first()
            _dates(data["internal_due_at"], plan.official_due_at if plan else None)
            changes["due_at"] = data["internal_due_at"]
        update_task(task=task, actor=actor, data=changes)
        if "assignees" in data: replace_assignees(task=task, actor=actor, assignee_ids=data["assignees"])
    _audit(project, actor, "tasks_bulk_updated", task_count=len(tasks), fields=sorted(data))
    return tasks


@transaction.atomic
def request_review(*, actor, project_id, task_id):
    project = _locked_project(actor, project_id)
    task = get_object_or_404(Task, pk=task_id, project=project, archived_at__isnull=True)
    if task.status == "done": raise ValidationError("Reopen the task before requesting review.")
    plan = get_object_or_404(TaskPlan, task=task)
    if not plan.reviewer_id or not plan.outcome_url:
        raise ValidationError("Choose a reviewer and link the deliverable before requesting review.")
    require_project_member(plan.reviewer, project)
    if plan.reviewer_id == actor.id:
        raise ValidationError("Ask another current team member to review this deliverable.")
    plan.review_state = "requested"; plan.reviewed_at = None; plan.review_note = ""
    plan.save(); _audit(project, actor, "review_requested", task_id=str(task.id))
    return plan


@transaction.atomic
def review_task(*, actor, project_id, task_id, approved, note):
    project = _locked_project(actor, project_id)
    task = get_object_or_404(Task, pk=task_id, project=project, archived_at__isnull=True)
    if task.status == "done": raise ValidationError("Completed deliverables cannot receive a new review.")
    plan = get_object_or_404(TaskPlan, task=task)
    if plan.reviewer_id != actor.id: raise PermissionDenied("Only the nominated reviewer can record this review.")
    if plan.review_state != "requested": raise ValidationError("This deliverable is not awaiting review.")
    plan.review_state = "approved" if approved else "changes_requested"
    plan.review_note = _text(note, "note", 1000, minimum=0 if approved else 3)
    plan.reviewed_at = timezone.now(); plan.save()
    _audit(project, actor, "task_reviewed", task_id=str(task.id), approved=approved)
    return plan


@transaction.atomic
def save_checklist(*, actor, project_id, task_id, data, item_id=None):
    project = _locked_project(actor, project_id)
    task = get_object_or_404(Task, pk=task_id, project=project, archived_at__isnull=True)
    if task.status == "done": raise ValidationError("Reopen the task before changing its checklist.")
    item = get_object_or_404(ChecklistItem, pk=item_id, task=task) if item_id else ChecklistItem(task=task)
    if "text" in data: item.text = _text(data["text"], "text", 300)
    if "checked" in data: item.checked = data["checked"]
    item.full_clean(); item.save()
    _audit(project, actor, "checklist_saved", task_id=str(task.id))
    return item


@transaction.atomic
def save_agreement(*, actor, project_id, body, expected_revision=None):
    project = _locked_project(actor, project_id, manager=True)
    agreement, created = TeamAgreement.objects.get_or_create(project=project, defaults={"body": _text(body, "body", 6000)})
    if expected_revision is not None and expected_revision != (0 if created else agreement.revision):
        raise ValidationError("This agreement changed. Reload it before saving; your local draft is retained.")
    if not created and agreement.body != body.strip():
        agreement.body = _text(body, "body", 6000); agreement.revision += 1; agreement.save()
    _audit(project, actor, "agreement_saved", revision=agreement.revision)
    return agreement


@transaction.atomic
def confirm_agreement(*, actor, project_id, revision):
    project = _locked_project(actor, project_id)
    agreement = get_object_or_404(TeamAgreement, project=project)
    if revision != agreement.revision: raise ValidationError("The agreement changed. Review the latest version first.")
    result, _ = AgreementConfirmation.objects.update_or_create(agreement=agreement, user=actor,
        defaults={"revision": revision, "confirmed_at": timezone.now()})
    _audit(project, actor, "agreement_confirmed", revision=revision)
    return result


@transaction.atomic
def save_resource(*, actor, project_id, data, resource_id=None):
    project = _locked_project(actor, project_id)
    resource = get_object_or_404(ResourceLink, pk=resource_id, project=project) if resource_id else ResourceLink(project=project, added_by=actor)
    if resource_id: resource_change(user=actor, resource=resource)
    if "title" in data: resource.title = _text(data["title"], "title", 150)
    if "url" in data: resource.url = safe_url(data["url"])
    if "description" in data: resource.description = _text(data["description"], "description", 1000, minimum=0)
    if "tags" in data:
        if not isinstance(data["tags"], list) or len(data["tags"]) > 10: raise ValidationError({"tags": "Use up to ten tags."})
        resource.tags = sorted(set(_text(t, "tags", 30).lower() for t in data["tags"]))
    if "pinned" in data: resource.pinned = data["pinned"]
    resource.full_clean(); resource.save(); _audit(project, actor, "resource_saved")
    return resource


@transaction.atomic
def delete_resource(*, actor, project_id, resource_id):
    project = _locked_project(actor, project_id)
    resource = get_object_or_404(ResourceLink, pk=resource_id, project=project)
    resource_change(user=actor, resource=resource); resource.delete(); _audit(project, actor, "resource_deleted")


def _editable_submission(project):
    plan, _ = SubmissionPlan.objects.get_or_create(project=project)
    if plan.submitted_at: raise ValidationError("A recorded submission receipt is read-only.")
    return plan


@transaction.atomic
def save_submission(*, actor, project_id, data):
    project = _locked_project(actor, project_id, manager=True)
    plan = _editable_submission(project)
    for field in ("official_due_at", "internal_due_at"):
        if field in data: setattr(plan, field, data[field])
    _dates(plan.internal_due_at, plan.official_due_at)
    plan.revision += 1; plan.full_clean(); plan.save()
    _audit(project, actor, "submission_plan_saved", revision=plan.revision)
    return plan


@transaction.atomic
def save_submission_item(*, actor, project_id, data, item_id=None):
    project = _locked_project(actor, project_id)
    plan = _editable_submission(project)
    item = get_object_or_404(SubmissionItem, pk=item_id, plan=plan) if item_id else SubmissionItem(plan=plan)
    if "text" in data: item.text = _text(data["text"], "text", 300)
    if "checked" in data: item.checked = data["checked"]
    item.full_clean(); item.save(); plan.revision += 1; plan.save()
    _audit(project, actor, "submission_checklist_saved", revision=plan.revision)
    return item


def _ready(plan):
    if not plan.items.exists() or plan.items.filter(checked=False).exists():
        raise ValidationError("Complete every item in the submission checklist first.")
    if Task.objects.filter(project=plan.project, archived_at__isnull=True).exclude(status="done").exists():
        raise ValidationError("Finish or archive every current task before confirming submission readiness.")


@transaction.atomic
def confirm_submission(*, actor, project_id, revision):
    project = _locked_project(actor, project_id)
    plan = _editable_submission(project); _ready(plan)
    if revision != plan.revision: raise ValidationError("The submission checklist changed. Review it again.")
    confirmation, _ = SubmissionConfirmation.objects.update_or_create(plan=plan, user=actor,
        defaults={"revision": revision, "confirmed_at": timezone.now()})
    _audit(project, actor, "submission_confirmed", revision=revision)
    return confirmation


@transaction.atomic
def record_receipt(*, actor, project_id, receipt_url, receipt_reference):
    project = _locked_project(actor, project_id, manager=True)
    plan = _editable_submission(project); _ready(plan)
    current = set(ProjectMembership.objects.active().filter(project=project, user__is_active=True).values_list("user_id", flat=True))
    confirmed = set(plan.confirmations.filter(revision=plan.revision).values_list("user_id", flat=True))
    if not current.issubset(confirmed): raise ValidationError("Every current active member must confirm this checklist revision.")
    plan.receipt_url = safe_url(receipt_url, optional=True)
    plan.receipt_reference = _text(receipt_reference, "receipt_reference", 200, minimum=0)
    if not plan.receipt_url and not plan.receipt_reference: raise ValidationError("Record a receipt link or submission reference.")
    plan.submitted_at = timezone.now(); plan.submitted_by = actor; plan.full_clean(); plan.save()
    _audit(project, actor, "submission_receipt_recorded")
    return plan


TEMPLATES = {
    "report": {"name": "Group report", "tasks": ["Read the brief and agree scope", "Research and collect sources", "Draft report sections", "Review citations and argument", "Proofread and package submission"], "checks": ["Meets the marking criteria", "Sources are cited", "Required format verified"]},
    "software": {"name": "Software project", "tasks": ["Agree requirements and acceptance criteria", "Design the solution", "Implement the agreed features", "Test and review the solution", "Prepare demo and submission"], "checks": ["Acceptance criteria checked", "Peer review completed", "Evidence and README included"]},
    "presentation": {"name": "Group presentation", "tasks": ["Agree key argument and roles", "Research supporting evidence", "Create slides", "Rehearse together", "Check timing and upload package"], "checks": ["Every member has a role", "Timing checked", "Sources and final format checked"]},
    "data_analysis": {"name": "Experiment and data analysis", "tasks": ["Read the brief and agree the research question", "Plan methods and permitted data collection", "Collect or prepare data and document its provenance", "Analyse results and record limitations", "Review reproducibility and package the report"], "checks": ["Method matches the assignment brief", "Data provenance and permitted use recorded", "Assumptions and limitations documented", "Another member can reproduce this step"]},
    "design": {"name": "Design project", "tasks": ["Agree the design brief and stakeholder needs", "Research constraints and relevant references", "Develop and compare design concepts", "Prototype and evaluate the chosen design", "Review the design rationale and submission package"], "checks": ["Decision links to a stated requirement", "Supporting evidence is recorded", "Evaluation and limitations documented"]},
    "research": {"name": "Thesis or long-term research", "tasks": ["Agree scope and milestones with the supervisor", "Review literature and maintain source records", "Plan methods and confirm required approvals", "Conduct the agreed work and maintain research records", "Analyse evidence and draft the thesis", "Review revisions and prepare the required submission"], "checks": ["Supervisor or brief requirements checked", "Required approvals verified before applicable work", "Evidence and source records retained", "Progress and limitations recorded"]},
}


@transaction.atomic
def instantiate_template(*, actor, project_id, template_key):
    project = _locked_project(actor, project_id, manager=True)
    if template_key not in TEMPLATES: raise ValidationError({"template": "Choose a supported assignment template."})
    template = TEMPLATES[template_key]
    milestones = [Milestone.objects.create(project=project, title=f"{template['name']}: scope and approach agreed"),
                  Milestone.objects.create(project=project, title=f"{template['name']}: reviewed submission ready")]
    tasks = []
    for index, title in enumerate(template["tasks"]):
        task = create_task(project=project, actor=actor, data={"title": title, "description": "Adapt this task to your assignment brief.", "due_at": project.due_at})
        TaskPlan.objects.create(task=task, milestone=milestones[0 if index < 2 else 1], acceptance="Check the assignment brief and agree the expected deliverable.")
        ChecklistItem.objects.bulk_create([ChecklistItem(task=task, text=text) for text in template["checks"]])
        if index: TaskDependency.objects.create(task=task, depends_on=tasks[-1])
        tasks.append(task)
    plan = _editable_submission(project)
    SubmissionItem.objects.bulk_create([SubmissionItem(plan=plan, text=t) for t in ("All required files included", "File names and format checked", "One designated member submits and records the receipt")])
    plan.revision += 1; plan.save()
    _audit(project, actor, "assignment_template_applied", template=template_key, task_count=len(tasks))
    return tasks


@transaction.atomic
def leave_project(*, actor, project_id, handover_user_id=None, new_owner_id=None):
    project = _locked_project(actor, project_id)
    membership = require_project_member(actor, project)
    if membership.role == "owner":
        if not new_owner_id: raise ValidationError({"new_owner": "Transfer ownership to another current member before leaving."})
        incoming = get_object_or_404(ProjectMembership.objects.active(), project=project, user_id=new_owner_id, user__is_active=True)
        transfer_ownership(actor=actor, project=project, new_owner=incoming.user)
    handover = None
    if handover_user_id:
        handover = get_object_or_404(ProjectMembership.objects.active(), project=project, user_id=handover_user_id, user__is_active=True).user
        if handover.id == actor.id: raise ValidationError("Choose another team member for task handover.")
    assigned = list(Task.objects.filter(project=project, assignments__user=actor, archived_at__isnull=True).distinct())
    if assigned and not handover: raise ValidationError({"handover_user": "Choose a teammate to receive your current task responsibilities."})
    for task in assigned:
        ids = set(task.assignments.values_list("user_id", flat=True)); ids.discard(actor.id); ids.add(handover.id)
        replace_assignees(task=task, actor=actor, assignee_ids=ids)
    actor.task_assignments.filter(task__project=project).delete()
    membership.removed_at = timezone.now(); membership.save(update_fields=("removed_at",))
    TaskPlan.objects.filter(task__project=project, reviewer=actor).update(reviewer=None, review_state="draft", reviewed_at=None)
    record_event(project=project, actor=actor, event_type="member_removed", target_type="membership", target_id=membership.id,
        metadata={"self_leave": True, "handed_over_task_count": len(assigned)})


@transaction.atomic
def create_join_link(*, actor, project_id, expires_at, max_uses):
    project = _locked_project(actor, project_id)
    require_project_owner(actor, project)
    now = timezone.now()
    if not now < expires_at <= now + timedelta(days=30): raise ValidationError({"expires_at": "Choose an expiry within the next 30 days."})
    if not 1 <= max_uses <= 50: raise ValidationError({"max_uses": "Choose one to fifty approved joins."})
    if JoinLink.objects.filter(project=project, created_at__gte=now-timedelta(hours=1)).count() >= 5:
        raise ValidationError("Create at most five join links per project per hour.")
    token = secrets.token_urlsafe(32)
    link = JoinLink.objects.create(project=project, created_by=actor, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=expires_at, max_uses=max_uses)
    _audit(project, actor, "join_link_created")
    return link, token


@transaction.atomic
def revoke_join_link(*, actor, project_id, link_id):
    project = _locked_project(actor, project_id); require_project_owner(actor, project)
    link = get_object_or_404(JoinLink, pk=link_id, project=project)
    link.revoked_at = timezone.now(); link.save()
    link.requests.filter(status="pending").update(status="rejected")
    _audit(project, actor, "join_link_revoked")


def request_join(*, actor, token):
    """Persist rate-limit attempts even when a token is invalid; expose no project contents."""
    with transaction.atomic():
        now = timezone.now()
        JoinAttempt.objects.get_or_create(user=actor, defaults={"window_started_at": now})
        attempt = JoinAttempt.objects.select_for_update().get(user=actor)
        if attempt.window_started_at <= now-timedelta(hours=1): attempt.window_started_at = now; attempt.count = 0
        if attempt.count >= 10: raise ValidationError("Try again later. At most ten join attempts are allowed per hour.")
        attempt.count += 1; attempt.save()
    with transaction.atomic():
        if not isinstance(token, str) or not 20 <= len(token) <= 100: raise ValidationError("This join code is unavailable.")
        link = JoinLink.objects.select_for_update().filter(token_hash=hashlib.sha256(token.encode()).hexdigest()).select_related("project").first()
        if not link or link.revoked_at or link.expires_at <= now or link.uses >= link.max_uses or link.project.archived_at:
            raise ValidationError("This join code is unavailable.")
        if ProjectMembership.objects.active().filter(project=link.project, user=actor).exists(): raise ValidationError("You already belong to this project.")
        request, _ = JoinRequest.objects.get_or_create(project=link.project, user=actor, status="pending", defaults={"link": link})
        return request


@transaction.atomic
def resolve_join(*, actor, project_id, request_id, approve):
    project = _locked_project(actor, project_id); require_project_owner(actor, project)
    request = get_object_or_404(JoinRequest.objects.select_for_update().select_related("user"), pk=request_id, project=project, status="pending")
    link = JoinLink.objects.select_for_update().get(pk=request.link_id)
    if approve:
        if link.revoked_at or link.expires_at <= timezone.now() or link.uses >= link.max_uses:
            raise ValidationError("This join link has expired, was revoked, or reached its limit.")
        if not request.user.is_active or not request.user.email_verified_at: raise ValidationError("The applicant must have an active verified account.")
        membership, created = ProjectMembership.objects.get_or_create(project=project, user=request.user, defaults={"role": "member"})
        if not created and membership.removed_at:
            membership.removed_at = None; membership.role = "member"; membership.joined_at = timezone.now(); membership.save()
        elif not created: raise ValidationError("The applicant is already a current member.")
        link.uses += 1; link.save(update_fields=("uses", "updated_at"))
        record_event(project=project, actor=actor, event_type="member_joined", target_type="membership", target_id=membership.id,
                     metadata={"approved_join_request": True})
    request.status = "approved" if approve else "rejected"; request.save()
    return request


@transaction.atomic
def copy_term(*, actor, term_id, year, name, project_ids):
    source = own_record(user=actor, model=Term, pk=term_id)
    target = create_term(actor=actor, university=source.university, year=year, name=name)
    if len(project_ids) > 20: raise ValidationError("Copy at most twenty projects at a time.")
    copied = []
    for project_id in dict.fromkeys(project_ids):
        source_project = project_access(user=actor, project_id=project_id)
        require_project_owner(actor, source_project)
        links = list(ProjectCourse.objects.filter(project=source_project, term=source, course__owner=actor))
        if not links: raise ValidationError("Choose projects associated with your source term.")
        project = create_project(actor=actor, name=(source_project.name[:75] + " · " + name[:20])[:100], description=source_project.description)
        ProjectCourse.objects.bulk_create([ProjectCourse(project=project, course=link.course, term=target) for link in links])
        milestone_map = {}
        for milestone in Milestone.objects.filter(project=source_project):
            milestone_map[milestone.id] = Milestone.objects.create(project=project, title=milestone.title)
        task_map = {}
        for task in Task.objects.filter(project=source_project, archived_at__isnull=True):
            task_map[task.id] = create_task(project=project, actor=actor, data={"title": task.title, "description": task.description, "priority": task.priority})
        for old_id, task in task_map.items():
            old_plan = TaskPlan.objects.filter(task_id=old_id).first()
            if old_plan:
                TaskPlan.objects.create(task=task, acceptance=old_plan.acceptance, tags=old_plan.tags, estimate_hours=old_plan.estimate_hours, parent=task_map.get(old_plan.parent_id), milestone=milestone_map.get(old_plan.milestone_id))
            ChecklistItem.objects.bulk_create([ChecklistItem(task=task, text=item.text) for item in ChecklistItem.objects.filter(task_id=old_id)])
        for edge in TaskDependency.objects.filter(task__project=source_project):
            if edge.task_id in task_map and edge.depends_on_id in task_map:
                TaskDependency.objects.create(task=task_map[edge.task_id], depends_on=task_map[edge.depends_on_id])
        for resource in ResourceLink.objects.filter(project=source_project):
            ResourceLink.objects.create(project=project, added_by=actor, title=resource.title, url=resource.url, description=resource.description, tags=resource.tags, pinned=resource.pinned)
        agreement = TeamAgreement.objects.filter(project=source_project).first()
        if agreement: TeamAgreement.objects.create(project=project, body=agreement.body)
        old_submission = SubmissionPlan.objects.filter(project=source_project).first()
        if old_submission:
            plan = SubmissionPlan.objects.create(project=project)
            SubmissionItem.objects.bulk_create([SubmissionItem(plan=plan, text=item.text) for item in old_submission.items.all()])
        copied.append(project)
    return target, copied
