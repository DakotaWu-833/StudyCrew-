"""Public output, membership and query-size regression checks for collections."""

from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from api.serializers import TaskSerializer
from api.tests.base import APIDomainTestCase
from meetings.models import Meeting, MeetingAttendance
from projects.models import Project, ProjectMembership
from tasks.models import Task, TaskAssignment, TaskComment
from tasks.selectors import task_for_member, tasks_for_project


class TaskCollectionEfficiencyTests(APIDomainTestCase):
    def setUp(self):
        super().setUp()
        self.tasks = []
        for number in range(10):
            task = Task.objects.create(project=self.project, created_by=self.owner, title=f"Task {number:02}")
            for user in (self.owner, self.member):
                TaskAssignment.objects.create(task=task, user=user, assigned_by=self.owner)
            TaskComment.objects.create(task=task, author=self.member, body="Visible comment")
            TaskComment.objects.create(task=task, author=self.owner, body="Hidden comment", deleted_at=timezone.now())
            self.tasks.append(task)

    def test_serialized_output_is_identical_and_query_count_is_constant(self):
        for size in (1, 5, 10):
            ids = [task.id for task in self.tasks[:size]]
            expected = TaskSerializer(Task.objects.filter(pk__in=ids).order_by("status", "due_at", "created_at", "id"), many=True).data
            with self.subTest(size=size), self.assertNumQueries(4):
                actual = TaskSerializer(
                    tasks_for_project(project=self.project, user=self.member).filter(pk__in=ids), many=True
                ).data
            self.assertEqual(actual, expected)
            self.assertTrue(all(task["comment_count"] == 1 for task in actual))
            self.assertTrue(all(len(task["assignees"]) == 2 for task in actual))

    def test_single_lookup_preserves_output_and_visible_comment_count(self):
        expected = TaskSerializer(self.tasks[0]).data
        with self.assertNumQueries(4):
            actual = TaskSerializer(task_for_member(task_id=self.tasks[0].id, user=self.member)).data
        self.assertEqual(actual, expected)

    def test_assignee_filter_does_not_change_other_assignees_or_duplicate_comment_counts(self):
        data = TaskSerializer(
            tasks_for_project(project=self.project, user=self.member, assignee_id=self.member.id), many=True
        ).data
        self.assertEqual(len(data), 10)
        self.assertTrue(all(item["comment_count"] == 1 for item in data))
        self.assertTrue(all(len(item["assignees"]) == 2 for item in data))

    def test_assignment_response_does_not_use_stale_prefetched_members(self):
        self.authenticate()
        response = self.client.put(
            f"/api/v1/tasks/{self.tasks[0].id}/assignees/",
            {"assignee_ids": [str(self.member.id)]}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([item["id"] for item in response.json()["assignees"]], [str(self.member.id)])


class MeetingCollectionPaginationTests(APIDomainTestCase):
    def setUp(self):
        super().setUp()
        self.reference = timezone.now()
        self.authenticate(self.member)

    def make_meeting(self, number=0, **overrides):
        values = {
            "project": self.project, "organiser": self.owner, "title": f"Session {number:02}",
            "starts_at": self.reference + timedelta(days=number + 1),
            "ends_at": self.reference + timedelta(days=number + 1, hours=1),
        }
        values.update(overrides)
        meeting = Meeting.objects.create(**values)
        MeetingAttendance.objects.create(meeting=meeting, user=self.member, response="accepted")
        return meeting

    def get_page(self, **query):
        return self.client.get("/api/v1/meetings/", {"project": str(self.project.id), **query})

    def test_default_five_item_pages_are_stably_ordered_without_overlap(self):
        meetings = [self.make_meeting(number) for number in range(12)]
        first, second, third = (self.get_page(page=number) for number in (1, 2, 3))
        for response in (first, second, third):
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["count"], 12)
        self.assertEqual([len(item.json()["results"]) for item in (first, second, third)], [5, 5, 2])
        ids = [item["id"] for response in (first, second, third) for item in response.json()["results"]]
        self.assertEqual(ids, [str(meeting.id) for meeting in meetings])
        self.assertIn("page=2", first.json()["next"])
        self.assertIsNone(third.json()["next"])

    def test_search_matches_title_agenda_location_and_organiser_display_name(self):
        title = self.make_meeting(0, title="Review launch")
        agenda = self.make_meeting(1, agenda="Deployment rehearsal")
        location = self.make_meeting(2, location="Library north")
        for search, expected in (("LAUNCH", title), ("rehearsal", agenda), ("north", location)):
            with self.subTest(search=search):
                results = self.get_page(search=search).json()["results"]
                self.assertEqual([item["id"] for item in results], [str(expected.id)])
        self.assertEqual(self.get_page(search="API Owner").json()["count"], 3)
        self.assertEqual(self.get_page(search="not-present").json()["count"], 0)

    def test_scope_and_status_follow_lifecycle_precedence_and_compose_with_search(self):
        scheduled = self.make_meeting(0)
        ended = self.make_meeting(1, starts_at=self.reference - timedelta(hours=2), ends_at=self.reference - timedelta(hours=1))
        cancelled = self.make_meeting(2, cancelled_at=self.reference)
        archived = self.make_meeting(3, cancelled_at=self.reference, archived_at=self.reference)
        for state, expected in (("scheduled", scheduled), ("ended", ended), ("cancelled", cancelled), ("archived", archived)):
            with self.subTest(state=state):
                result = self.get_page(scope="all", state=state, search="Session").json()
                self.assertEqual(result["count"], 1)
                self.assertEqual(result["results"][0]["id"], str(expected.id))
        self.assertEqual(self.get_page().json()["count"], 3)
        self.assertEqual(self.get_page(scope="archived").json()["count"], 1)
        self.assertEqual(self.get_page(scope="archived", state="ended").json()["count"], 0)

    def test_malformed_and_unbounded_query_fields_are_rejected(self):
        for query in ({"state": "future"}, {"scope": "secret"}, {"search": "x" * 121}, {"page": "last"},
                      {"page": 0}, {"page": 1_000_001}, {"page_size": 0}, {"page_size": 51}):
            with self.subTest(query=query):
                response = self.get_page(**query)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(response.json()["error"]["code"], "validation_error")
        self.assertEqual(self.get_page(page=2).status_code, 404)

    def test_outsiders_cannot_search_and_other_projects_never_leak(self):
        self.make_meeting()
        other = Project.objects.create(name="Private collection", created_by=self.outsider)
        ProjectMembership.objects.create(project=other, user=self.outsider, role="owner")
        self.make_meeting(1, project=other, organiser=self.outsider)
        self.assertEqual(self.get_page(search="Session", scope="all").json()["count"], 1)
        self.authenticate(self.outsider)
        self.assertEqual(self.get_page(search="Session").status_code, 403)

    def test_profile_and_attendance_reads_do_not_grow_per_visible_record(self):
        self.make_meeting()
        with CaptureQueriesContext(connection) as one:
            response = self.get_page()
        self.assertEqual(response.status_code, 200)
        for number in range(1, 10):
            self.make_meeting(number)
        with CaptureQueriesContext(connection) as five:
            response = self.get_page()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 5)
        self.assertEqual(len(one), len(five))
        self.assertLessEqual(len(five), 12)
        self.assertTrue(all(item["attendance_counts"]["accepted"] == 1 for item in response.json()["results"]))
