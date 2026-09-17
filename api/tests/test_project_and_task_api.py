from datetime import timedelta

from django.utils import timezone

from activity.models import ActivityEvent
from api.tests.base import APIDomainTestCase
from projects.models import Project, ProjectMembership
from projects.services import archive_project
from tasks.models import Task, TaskAssignment


class ProjectAndTaskAPITests(APIDomainTestCase):
    def test_project_full_crud_uses_soft_delete(self):
        self.authenticate()
        created = self.client.post(
            "/api/v1/projects/",
            {"name": "New delivery project", "description": "A clear project"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        project_id = created.json()["id"]
        self.assertEqual(self.client.get(f"/api/v1/projects/{project_id}/").status_code, 200)
        updated = self.client.put(
            f"/api/v1/projects/{project_id}/",
            {"name": "Updated delivery project", "description": "Updated", "due_at": None},
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(updated.json()["name"], "Updated delivery project")
        rejected_field = self.client.patch(
            f"/api/v1/projects/{project_id}/",
            {"created_by": str(self.member.id)},
            format="json",
        )
        self.assertEqual(rejected_field.status_code, 400)
        self.assertIn("created_by", rejected_field.json()["error"]["fields"])
        deleted = self.client.delete(f"/api/v1/projects/{project_id}/")
        self.assertEqual(deleted.status_code, 204)
        project = Project.objects.get(id=project_id)
        self.assertIsNotNone(project.archived_at)
        self.assertTrue(
            ActivityEvent.objects.filter(
                project=project, event_type=ActivityEvent.Type.PROJECT_ARCHIVED
            ).exists()
        )

    def test_member_cannot_update_or_archive_project(self):
        self.authenticate(self.member)
        patch = self.client.patch(
            f"/api/v1/projects/{self.project.id}/", {"name": "Taken over"}, format="json"
        )
        self.assertEqual(patch.status_code, 403)
        self.assertEqual(self.client.delete(f"/api/v1/projects/{self.project.id}/").status_code, 403)

    def test_archived_project_history_is_read_only(self):
        task = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Retained historical task",
        )
        archive_project(project=self.project, actor=self.owner)
        self.authenticate(self.owner)

        active_projects = self.client.get("/api/v1/projects/")
        self.assertEqual(active_projects.status_code, 200)
        self.assertNotIn(
            str(self.project.id),
            {project["id"] for project in active_projects.json()["results"]},
        )
        self.assertEqual(self.client.get(f"/api/v1/projects/{self.project.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/tasks/{task.id}/").status_code, 200)
        self.assertEqual(
            self.client.get("/api/v1/tasks/", {"project": str(self.project.id)}).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/tasks/",
                {"project": str(self.project.id), "title": "Must not be created"},
                format="json",
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/v1/tasks/{task.id}/",
                {"title": "Must not be changed"},
                format="json",
            ).status_code,
            400,
        )
        archived_projects = self.client.get("/api/v1/projects/", {"scope": "archived"})
        self.assertEqual(archived_projects.status_code, 200)
        self.assertEqual(
            {project["id"] for project in archived_projects.json()["results"]},
            {str(self.project.id)},
        )

    def test_project_put_requires_a_complete_replace_payload(self):
        self.authenticate(self.owner)

        response = self.client.put(
            f"/api/v1/projects/{self.project.id}/",
            {"name": "Incomplete replacement"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            set(response.json()["error"]["fields"]),
            {"description", "due_at"},
        )

    def test_outsider_cannot_retrieve_project_or_infer_content(self):
        self.authenticate(self.outsider)
        response = self.client.get(f"/api/v1/projects/{self.project.id}/")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(self.project.name, response.content.decode())

    def test_task_full_crud_search_and_soft_archive(self):
        self.authenticate(self.owner)
        created = self.client.post(
            "/api/v1/tasks/",
            {
                "project": str(self.project.id),
                "title": "Write API documentation",
                "description": "Include request and response examples",
                "priority": "high",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content)
        task_id = created.json()["id"]
        listed = self.client.get(
            f"/api/v1/tasks/?project={self.project.id}&q=documentation&priority=high"
        )
        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertEqual(listed.json()["count"], 1)
        updated = self.client.put(
            f"/api/v1/tasks/{task_id}/",
            {
                "title": "Publish API documentation",
                "description": "Polished examples",
                "priority": "urgent",
                "due_at": None,
            },
            format="json",
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(updated.json()["priority"], "urgent")
        self.assertEqual(self.client.delete(f"/api/v1/tasks/{task_id}/").status_code, 204)
        self.assertIsNotNone(Task.objects.get(id=task_id).archived_at)
        active = self.client.get("/api/v1/tasks/", {"project": str(self.project.id)})
        archived = self.client.get(
            "/api/v1/tasks/", {"project": str(self.project.id), "scope": "archived"}
        )
        all_records = self.client.get(
            "/api/v1/tasks/", {"project": str(self.project.id), "scope": "all"}
        )
        self.assertNotIn(task_id, {item["id"] for item in active.json()["results"]})
        self.assertIn(task_id, {item["id"] for item in archived.json()["results"]})
        self.assertIn(task_id, {item["id"] for item in all_records.json()["results"]})

    def test_task_list_applies_all_valid_query_filters_together(self):
        now = timezone.now()
        matching = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Release documentation review",
            status=Task.Status.IN_PROGRESS,
            priority=Task.Priority.HIGH,
            due_at=now + timedelta(days=2),
        )
        TaskAssignment.objects.create(
            task=matching,
            user=self.member,
            assigned_by=self.owner,
        )
        Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Release documentation but wrong status",
            status=Task.Status.TODO,
            priority=Task.Priority.HIGH,
            due_at=now + timedelta(days=2),
        )
        Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Release documentation but overdue",
            status=Task.Status.IN_PROGRESS,
            priority=Task.Priority.HIGH,
            due_at=now - timedelta(days=1),
        )
        self.authenticate(self.owner)

        response = self.client.get(
            "/api/v1/tasks/",
            {
                "project": str(self.project.id),
                "q": "documentation",
                "status": Task.Status.IN_PROGRESS,
                "priority": Task.Priority.HIGH,
                "assignee": str(self.member.id),
                "due": "upcoming",
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(matching.id))

    def test_task_assignment_and_transition_actions(self):
        task = Task.objects.create(
            project=self.project, created_by=self.owner, title="Finish tested workflow"
        )
        self.authenticate(self.owner)
        response = self.client.put(
            f"/api/v1/tasks/{task.id}/assignees/",
            {"assignee_ids": [str(self.member.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.authenticate(self.member)
        blocked = self.client.post(
            f"/api/v1/tasks/{task.id}/transition/",
            {"status": "blocked", "blocker_note": "Waiting for review"},
            format="json",
        )
        self.assertEqual(blocked.status_code, 200, blocked.content)
        done = self.client.post(
            f"/api/v1/tasks/{task.id}/transition/", {"status": "done"}, format="json"
        )
        self.assertEqual(done.status_code, 200, done.content)
        self.assertIsNotNone(done.json()["completed_at"])

    def test_invalid_and_cross_project_assignees_leave_state_unchanged(self):
        task = Task.objects.create(
            project=self.project, created_by=self.owner, title="Protected assignment"
        )
        self.authenticate(self.owner)
        response = self.client.put(
            f"/api/v1/tasks/{task.id}/assignees/",
            {"assignee_ids": [str(self.outsider.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(task.assignments.count(), 0)

    def test_archived_task_rejects_update_and_assignee_mutations(self):
        task = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Retained evidence",
            archived_at=timezone.now(),
        )
        self.authenticate(self.owner)

        updated = self.client.patch(
            f"/api/v1/tasks/{task.id}/",
            {"title": "Mutated evidence"},
            format="json",
        )
        assigned = self.client.put(
            f"/api/v1/tasks/{task.id}/assignees/",
            {"assignee_ids": [str(self.member.id)]},
            format="json",
        )

        self.assertEqual(updated.status_code, 400)
        self.assertEqual(assigned.status_code, 400)
        task.refresh_from_db()
        self.assertEqual(task.title, "Retained evidence")
        self.assertFalse(task.assignments.exists())

    def test_task_put_requires_a_complete_replace_payload(self):
        task = Task.objects.create(
            project=self.project,
            created_by=self.owner,
            title="Complete replacement contract",
        )
        self.authenticate(self.owner)

        response = self.client.put(f"/api/v1/tasks/{task.id}/", {}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            set(response.json()["error"]["fields"]),
            {"title", "description", "priority", "due_at"},
        )

    def test_task_list_requires_project_and_sqli_text_is_data(self):
        self.authenticate(self.owner)
        self.assertEqual(self.client.get("/api/v1/tasks/").status_code, 400)
        injection = "' OR 1=1 --"
        response = self.client.get(
            "/api/v1/tasks/", {"project": str(self.project.id), "q": injection}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)
        invalid_scope = self.client.get(
            "/api/v1/tasks/", {"project": str(self.project.id), "scope": "deleted"}
        )
        self.assertEqual(invalid_scope.status_code, 400)

    def test_outsider_task_idor_is_denied(self):
        task = Task.objects.create(
            project=self.project, created_by=self.owner, title="Private task content"
        )
        self.authenticate(self.outsider)
        response = self.client.get(f"/api/v1/tasks/{task.id}/")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("Private task content", response.content.decode())
