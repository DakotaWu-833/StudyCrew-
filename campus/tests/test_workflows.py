from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.utils import timezone

from api.tests.base import APIDomainTestCase
from projects.models import ProjectMembership
from projects.services import create_project
from tasks.models import Task
from tasks.services import create_task, replace_assignees, transition_task

from campus import selectors, services
from campus.models import (Term, Course, ProjectCourse, TaskPlan, TaskDependency,
    ChecklistItem, AgreementConfirmation, SubmissionPlan, SubmissionConfirmation,
    JoinAttempt, JoinRequest, ResourceLink)


class CampusWorkflowTests(APIDomainTestCase):
    def test_all_six_templates_create_real_workflow_structure(self):
        self.assertEqual(len(services.TEMPLATES), 6)
        for key in services.TEMPLATES:
            project = create_project(actor=self.owner, name=f"Template {key}", description="")
            tasks = services.instantiate_template(actor=self.owner, project_id=project.id, template_key=key)
            self.assertGreaterEqual(len(tasks), 5)
            self.assertEqual(TaskDependency.objects.filter(task__project=project).count(), len(tasks)-1)
            self.assertEqual(services.Milestone.objects.filter(project=project).count(), 2)
            self.assertTrue(all(task.academic_checklist.count() >= 3 and task.academic_plan.milestone_id for task in tasks))
            self.assertEqual(SubmissionPlan.objects.get(project=project).items.count(), 3)

    def task(self, title="Prepare final report"):
        return create_task(project=self.project, actor=self.owner, data={"title": title})

    def test_metadata_is_private_and_does_not_grant_membership(self):
        term = services.create_term(actor=self.owner, university="Example University", year=2026, name="Semester 1")
        course = services.create_course(actor=self.owner, university="Example University", code="COMP1001", name="Project work")
        services.link_course(actor=self.owner, project_id=self.project.id, course_id=course.id, term_id=term.id)
        self.assertEqual(len(selectors.overview(self.owner)["courses"]), 1)
        self.assertEqual(selectors.overview(self.member)["courses"], [])
        with self.assertRaises(Http404): selectors.project_plan(user=self.outsider, project_id=self.project.id)
        with self.assertRaises(Http404): services.archive_term(actor=self.member, term_id=term.id)

    def test_course_and_term_university_must_match(self):
        term = services.create_term(actor=self.owner, university="One University", year=2026, name="Term 1")
        course = services.create_course(actor=self.owner, university="Other University", code="TEST1", name="Course")
        with self.assertRaises(ValidationError): services.link_course(actor=self.owner, project_id=self.project.id, course_id=course.id, term_id=term.id)
        self.assertFalse(ProjectCourse.objects.exists())

    def test_template_creates_real_tasks_and_completion_gates(self):
        tasks = services.instantiate_template(actor=self.owner, project_id=self.project.id, template_key="report")
        self.assertEqual(len(tasks), 5)
        self.assertEqual(Task.objects.filter(project=self.project).count(), 5)
        self.assertEqual(TaskDependency.objects.count(), 4)
        with self.assertRaises(ValidationError): transition_task(task=tasks[0], actor=self.owner, status="done")
        tasks[0].refresh_from_db()
        for item in tasks[0].academic_checklist.all():
            services.save_checklist(actor=self.owner, project_id=self.project.id, task_id=tasks[0].id, item_id=item.id, data={"checked": True})
        transition_task(task=tasks[0], actor=self.owner, status="done")
        self.assertEqual(Task.objects.get(pk=tasks[0].id).status, "done")

    def test_dependency_cycles_roll_back(self):
        first, second = self.task("First task"), self.task("Second task")
        services.save_task_plan(actor=self.owner, project_id=self.project.id, task_id=second.id, data={"dependencies": [first.id]})
        with self.assertRaises(ValidationError): services.save_task_plan(actor=self.owner, project_id=self.project.id, task_id=first.id, data={"dependencies": [second.id]})
        self.assertFalse(TaskDependency.objects.filter(task=first).exists())
        with self.assertRaises(ValidationError): services.save_task_plan(actor=self.owner, project_id=self.project.id, task_id=first.id, data={"dependencies": [first.id]})

    def test_parent_cycles_and_incomplete_children_are_blocked(self):
        first = self.task("Parent task")
        second = services.create_subtask(actor=self.owner, project_id=self.project.id, title="Child task", parent=first.id)
        with self.assertRaises(ValidationError): services.save_task_plan(actor=self.owner, project_id=self.project.id, task_id=first.id, data={"parent": second.id})
        with self.assertRaises(ValidationError): transition_task(task=first, actor=self.owner, status="done")
        first.refresh_from_db()
        transition_task(task=second, actor=self.owner, status="done")
        transition_task(task=first, actor=self.owner, status="done")

    def test_task_relations_cannot_cross_projects(self):
        other_project = create_project(actor=self.owner, name="Other private project")
        other = create_task(project=other_project, actor=self.owner, data={"title": "Other private task"})
        current = self.task()
        with self.assertRaises(Http404): services.save_task_plan(actor=self.owner, project_id=self.project.id, task_id=current.id, data={"parent": other.id})
        with self.assertRaises(ValidationError): services.save_task_plan(actor=self.owner, project_id=self.project.id, task_id=current.id, data={"dependencies": [other.id]})

    def test_internal_deadline_cannot_be_after_official(self):
        task = self.task(); now = timezone.now()
        with self.assertRaises(ValidationError): services.save_task_plan(actor=self.owner, project_id=self.project.id, task_id=task.id, data={"official_due_at": now, "internal_due_at": now+timedelta(days=1)})
        self.assertFalse(TaskPlan.objects.filter(task=task).exists())

    def test_review_requires_nominated_member_and_completion_approval(self):
        task = self.task()
        services.save_task_plan(actor=self.owner, project_id=self.project.id, task_id=task.id, data={"reviewer": self.member.id, "outcome_url": "https://example.com/final"})
        services.request_review(actor=self.owner, project_id=self.project.id, task_id=task.id)
        with self.assertRaises(PermissionDenied): services.review_task(actor=self.owner, project_id=self.project.id, task_id=task.id, approved=True, note="")
        with self.assertRaises(ValidationError): transition_task(task=task, actor=self.owner, status="done")
        task.refresh_from_db()
        services.review_task(actor=self.member, project_id=self.project.id, task_id=task.id, approved=True, note="Checked against the brief")
        transition_task(task=task, actor=self.owner, status="done")

    def test_agreement_changes_require_fresh_confirmation(self):
        agreement = services.save_agreement(actor=self.owner, project_id=self.project.id, body="Discuss blockers at each weekly meeting.")
        services.confirm_agreement(actor=self.member, project_id=self.project.id, revision=agreement.revision)
        updated = services.save_agreement(actor=self.owner, project_id=self.project.id, body="Discuss blockers and review deadlines each week.")
        self.assertEqual(updated.revision, 2)
        with self.assertRaises(ValidationError): services.confirm_agreement(actor=self.member, project_id=self.project.id, revision=1)
        self.assertFalse(AgreementConfirmation.objects.filter(agreement=agreement, revision=2).exists())

    def test_submission_requires_complete_checks_tasks_and_all_members(self):
        task = self.task()
        item = services.save_submission_item(actor=self.owner, project_id=self.project.id, data={"text": "Files checked", "checked": True})
        plan = item.plan; plan.refresh_from_db()
        with self.assertRaises(ValidationError): services.confirm_submission(actor=self.owner, project_id=self.project.id, revision=plan.revision)
        transition_task(task=task, actor=self.owner, status="done")
        plan.refresh_from_db()
        services.confirm_submission(actor=self.owner, project_id=self.project.id, revision=plan.revision)
        with self.assertRaises(ValidationError): services.record_receipt(actor=self.owner, project_id=self.project.id, receipt_url="", receipt_reference="Confirmed upload 123")
        services.confirm_submission(actor=self.member, project_id=self.project.id, revision=plan.revision)
        receipt = services.record_receipt(actor=self.owner, project_id=self.project.id, receipt_url="https://example.com/receipt", receipt_reference="Upload 123")
        self.assertIsNotNone(receipt.submitted_at)
        with self.assertRaises(ValidationError): services.save_submission_item(actor=self.owner, project_id=self.project.id, item_id=item.id, data={"checked": False})

    def test_submission_changes_invalidate_confirmation_revision(self):
        item = services.save_submission_item(actor=self.owner, project_id=self.project.id, data={"text": "Ready", "checked": True})
        plan = item.plan; plan.refresh_from_db()
        services.confirm_submission(actor=self.member, project_id=self.project.id, revision=plan.revision)
        old_revision = plan.revision
        services.save_submission_item(actor=self.owner, project_id=self.project.id, item_id=item.id, data={"text": "Check again"})
        plan.refresh_from_db(); self.assertGreater(plan.revision, old_revision)
        self.assertFalse(SubmissionConfirmation.objects.filter(plan=plan, revision=plan.revision).exists())

    def test_resources_validate_url_and_author_permission(self):
        for url in ("javascript:alert(1)", "http://127.0.0.1/test", "https://user:pass@example.com/file", "http://localhost/"):
            with self.assertRaises(ValidationError): services.save_resource(actor=self.member, project_id=self.project.id, data={"title": "Unsafe resource", "url": url})
        resource = services.save_resource(actor=self.owner, project_id=self.project.id, data={"title": "Assignment brief", "url": "https://example.com/brief", "tags": ["BRIEF", "brief"], "pinned": True})
        self.assertEqual(resource.tags, ["brief"])
        with self.assertRaises(PermissionDenied): services.save_resource(actor=self.member, project_id=self.project.id, resource_id=resource.id, data={"pinned": False})
        with self.assertRaises(Http404): services.delete_resource(actor=self.outsider, project_id=self.project.id, resource_id=resource.id)

    def test_search_and_personal_todos_are_membership_scoped(self):
        task = self.task("Private report deadline")
        replace_assignees(task=task, actor=self.owner, assignee_ids=[self.member.id])
        services.save_resource(actor=self.owner, project_id=self.project.id, data={"title": "Private report brief", "url": "https://example.com/brief"})
        self.assertEqual(len(selectors.personal_todos(user=self.member)["results"]), 1)
        self.assertEqual(selectors.personal_todos(user=self.outsider)["results"], [])
        private_search = selectors.search(user=self.outsider, query="Private")
        self.assertEqual(private_search["total"], 0)
        self.assertTrue(all(not private_search[key] for key in private_search["counts"]))
        self.assertEqual(len(selectors.search(user=self.member, query="report")["tasks"]), 1)

    def test_member_leave_requires_handover_and_revokes_access(self):
        task = self.task(); replace_assignees(task=task, actor=self.owner, assignee_ids=[self.member.id])
        with self.assertRaises(ValidationError): services.leave_project(actor=self.member, project_id=self.project.id)
        self.assertTrue(ProjectMembership.objects.active().filter(project=self.project, user=self.member).exists())
        services.leave_project(actor=self.member, project_id=self.project.id, handover_user_id=self.owner.id)
        self.assertEqual(set(task.assignees.values_list("id", flat=True)), {self.owner.id})
        with self.assertRaises(Http404): selectors.project_plan(user=self.member, project_id=self.project.id)

    def test_owner_leave_transfers_owner_and_rolls_back_when_handover_missing(self):
        task = self.task(); replace_assignees(task=task, actor=self.owner, assignee_ids=[self.owner.id])
        with self.assertRaises(ValidationError): services.leave_project(actor=self.owner, project_id=self.project.id, new_owner_id=self.member.id)
        self.assertTrue(ProjectMembership.objects.filter(project=self.project, user=self.owner, role="owner").exists())
        services.leave_project(actor=self.owner, project_id=self.project.id, new_owner_id=self.member.id, handover_user_id=self.member.id)
        self.assertTrue(ProjectMembership.objects.active().filter(project=self.project, user=self.member, role="owner").exists())
        self.assertEqual(set(task.assignees.values_list("id", flat=True)), {self.member.id})

    def test_join_link_requires_approval_before_private_reads(self):
        link, token = services.create_join_link(actor=self.owner, project_id=self.project.id, expires_at=timezone.now()+timedelta(days=1), max_uses=1)
        request = services.request_join(actor=self.outsider, token=token)
        self.assertFalse(ProjectMembership.objects.active().filter(project=self.project, user=self.outsider).exists())
        with self.assertRaises(Http404): selectors.project_plan(user=self.outsider, project_id=self.project.id)
        self.assertIsNone(selectors.overview(self.outsider)["join_requests"][0]["project"])
        services.resolve_join(actor=self.owner, project_id=self.project.id, request_id=request.id, approve=True)
        self.assertEqual(selectors.project_plan(user=self.outsider, project_id=self.project.id)["project"]["name"], self.project.name)
        link.refresh_from_db(); self.assertEqual(link.uses, 1)

    def test_revoked_join_link_rejects_pending_applicant(self):
        link, token = services.create_join_link(actor=self.owner, project_id=self.project.id, expires_at=timezone.now()+timedelta(days=1), max_uses=5)
        request = services.request_join(actor=self.outsider, token=token)
        services.revoke_join_link(actor=self.owner, project_id=self.project.id, link_id=link.id)
        request.refresh_from_db(); self.assertEqual(request.status, "rejected")
        with self.assertRaises(ValidationError): services.request_join(actor=self.outsider, token=token)

    def test_invalid_join_attempts_persist_and_are_limited(self):
        for _ in range(10):
            with self.assertRaises(ValidationError): services.request_join(actor=self.outsider, token="a" * 40)
        self.assertEqual(JoinAttempt.objects.get(user=self.outsider).count, 10)
        with self.assertRaisesMessage(ValidationError, "Try again later"):
            services.request_join(actor=self.outsider, token="b" * 40)

    def test_term_copy_resets_dates_reviews_completion_and_members(self):
        term = services.create_term(actor=self.owner, university="Example University", year=2026, name="Semester 1")
        course = services.create_course(actor=self.owner, university="Example University", code="COMP1001", name="Project work")
        services.link_course(actor=self.owner, project_id=self.project.id, course_id=course.id, term_id=term.id)
        tasks = services.instantiate_template(actor=self.owner, project_id=self.project.id, template_key="software")
        services.save_resource(actor=self.owner, project_id=self.project.id, data={"title": "Shared brief", "url": "https://example.com/brief"})
        new_term, projects = services.copy_term(actor=self.owner, term_id=term.id, year=2027, name="Semester 1", project_ids=[self.project.id])
        copied = projects[0]
        self.assertEqual(Task.objects.filter(project=copied).count(), 5)
        self.assertFalse(Task.objects.filter(project=copied).exclude(status="todo").exists())
        self.assertEqual(ProjectMembership.objects.active().filter(project=copied).count(), 1)
        self.assertEqual(ResourceLink.objects.filter(project=copied).count(), 1)
        self.assertEqual(TaskDependency.objects.filter(task__project=copied).count(), 4)
        self.assertTrue(ProjectCourse.objects.filter(project=copied, term=new_term).exists())

    def test_archived_project_plan_is_read_only(self):
        task = self.task(); self.project.archived_at = timezone.now(); self.project.save()
        with self.assertRaises(ValidationError): services.save_task_plan(actor=self.owner, project_id=self.project.id, task_id=task.id, data={"acceptance": "Changed"})
        self.assertEqual(selectors.project_plan(user=self.owner, project_id=self.project.id)["tasks"][0]["title"], task.title)

    def test_task_pages_and_choices_retain_tasks_after_old_cap(self):
        tasks = [Task(project=self.project, created_by=self.owner, title=f"Task {index:04d}") for index in range(505)]
        Task.objects.bulk_create(tasks)
        plan = selectors.project_plan(user=self.owner, project_id=self.project.id, page=11)
        self.assertEqual(plan["task_pagination"], {"total": 505, "page": 11, "page_size": 50, "pages": 11})
        self.assertEqual(len(plan["tasks"]), 5)
        self.assertEqual(len(plan["task_choices"]), 505)
        services.save_task_plan(actor=self.owner, project_id=self.project.id, task_id=plan["tasks"][-1]["id"], data={"acceptance": "Available beyond the former cap"})

    def test_tag_filter_runs_before_pagination_and_old_cap(self):
        ResourceLink.objects.bulk_create([ResourceLink(project=self.project, added_by=self.owner, title=f"Resource {i:04d}", url="https://example.com/file", tags=["old"] if i < 500 else ["target"]) for i in range(505)])
        page = selectors.resources(user=self.member, project_id=self.project.id, tag="target")
        self.assertEqual(page["total"], 5)
        self.assertEqual(len(page["results"]), 5)
        self.assertEqual(selectors.resources(user=self.member, project_id=self.project.id, page=21)["total"], 505)


class CampusAPITests(APIDomainTestCase):
    def test_api_requires_mfa_and_scopes_project(self):
        self.assertEqual(self.client.get("/api/v1/campus/overview/").status_code, 401)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/api/v1/campus/overview/").status_code, 401)
        self.authenticate(self.outsider)
        self.assertEqual(self.client.get(f"/api/v1/campus/projects/{self.project.id}/").status_code, 404)

    def test_template_and_existing_done_route_enforce_checklist(self):
        self.authenticate()
        response = self.client.post(f"/api/v1/campus/projects/{self.project.id}/template/", {"template": "report"}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        task_id = response.data["tasks"][0]
        response = self.client.post(f"/api/v1/tasks/{task_id}/transition/", {"status": "done"}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        task = Task.objects.get(pk=task_id); self.assertEqual(task.status, "todo")

    def test_unsafe_resource_url_gets_validation_error(self):
        self.authenticate()
        response = self.client.post(f"/api/v1/campus/projects/{self.project.id}/resources/", {"title": "Unsafe", "url": "javascript:alert(1)"}, format="json")
        self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(ResourceLink.objects.exists())

    def test_authenticated_mutation_still_requires_csrf(self):
        from rest_framework.test import APIClient
        client = APIClient(enforce_csrf_checks=True)
        self.authenticate(client=client)
        response = client.post("/api/v1/campus/terms/", {"university": "Example", "year": 2026, "name": "Term 1"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Term.objects.exists())

    def test_member_cannot_create_join_link_or_apply_template(self):
        self.authenticate(self.member)
        response = self.client.post(f"/api/v1/campus/projects/{self.project.id}/join-links/", {"expires_at": (timezone.now()+timedelta(days=1)).isoformat(), "max_uses": 5}, format="json")
        self.assertEqual(response.status_code, 403)
        response = self.client.post(f"/api/v1/campus/projects/{self.project.id}/template/", {"template": "software"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Task.objects.exists())
